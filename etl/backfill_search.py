"""
backfill_search.py
Historical backfill pipeline for the YouTube Reading Intelligence Dashboard.

Reads config/backfill_windows.csv for the list of monthly windows to process.
Updates the status column in that file to 'completed' after each window finishes —
this is your local progress tracker so you can see where you are without querying BigQuery.

BigQuery search_runs acts as a second idempotency layer: even if the CSV status is wrong,
the script will never double-fetch a window that already exists in search_runs.

All significant events are written to logs/pipeline_YYYYMMDD.log via logger.py.

For each keyword × pending window:
  1. Check CSV status (skip if completed)
  2. Check BigQuery idempotency (skip if already in search_runs)
  3. Call YouTube search.list  (~100 units)
  4. Call YouTube videos.list  (~1 unit/video, up to 50)
  5. Call YouTube channels.list (~1 unit/channel, deduplicated)
  6. Save raw JSON to Cloud Storage
  7. MERGE videos + channels into BigQuery
  8. Insert search_run + search_results rows
  9. Mark window as completed in backfill_windows.csv
  10. Log all outcomes via logger.py

Usage (run from repo root):
    # Dry run first — always
    python etl/backfill_search.py --run demo --dry_run

    # Demo backfill (priority=demo, Jan 2025–May 2026)
    python etl/backfill_search.py --run demo

    # Full historical backfill (all windows, Jan 2020–May 2026)
    python etl/backfill_search.py --run full

    # Single keyword
    python etl/backfill_search.py --run demo --keyword_id KW0004

Quota estimate:
    demo (17 months) × N keywords × ~150 units/window
    full (77 months) × N keywords × ~150 units/window
    Run --dry_run first to see the exact estimate for your keyword count.

Requirements:
    pip install google-api-python-client google-cloud-bigquery google-cloud-storage python-dotenv
"""

import os
import sys
import json
import uuid
import argparse
import csv
import time
from datetime import datetime, timezone, date
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.cloud import bigquery, storage

# ── Path setup — must come before local imports ──────────────
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(__file__))

from logger import (
    log_run_start,
    log_summary,
    log_window_start,
    log_window_complete,
    log_window_skip,
    log_zero_results,
    log_failure,
)

from config.constants import (
    PROJECT_ID,
    REGION,
    FULL_DATASET,
    BUCKET_NAME,
    GCS_BACKFILL_PREFIX,
    KEYWORDS_CSV,
    REGISTRY_CSV,
    WINDOWS_CSV,
    TABLE_SEARCH_RUNS,
    TABLE_SEARCH_RESULTS,
    TABLE_VIDEOS,
    TABLE_CHANNELS,
)

# ─────────────────────────────────────────────
# Load environment + clients
# ─────────────────────────────────────────────
load_dotenv()

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY_2"]

bq_client  = bigquery.Client(project=PROJECT_ID, location=REGION)
gcs_client = storage.Client(project=PROJECT_ID)
youtube    = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


# ─────────────────────────────────────────────
# CSV loaders
# ─────────────────────────────────────────────
def load_keywords(keyword_id_filter: str | None) -> list[dict]:
    """
    Load active keywords by joining keywords.csv and keyword_registry.csv on keyword_id.
    Only returns rows where keyword_registry.active = TRUE.
    Optionally filters to a single keyword_id via --keyword_id argument.
    """
    active_ids = set()
    with open(REGISTRY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("active", "").upper() == "TRUE":
                active_ids.add(row["keyword_id"])

    rows = []
    with open(KEYWORDS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row["keyword_id"] not in active_ids:
                continue
            if keyword_id_filter and row["keyword_id"] != keyword_id_filter:
                continue
            rows.append(row)

    if not rows:
        raise ValueError(
            f"No active keywords found (filter={keyword_id_filter}). "
            f"Check active=TRUE in config/keyword_registry.csv."
        )
    return rows


def load_windows(run_mode: str) -> list[dict]:
    """
    Load pending windows from config/backfill_windows.csv.
    run_mode='demo' → only rows where priority=demo
    run_mode='full' → all rows
    Skips rows where status='completed'.
    """
    all_rows = []
    with open(WINDOWS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if run_mode == "demo" and row["priority"] != "demo":
                continue
            all_rows.append(row)

    pending   = [r for r in all_rows if r["status"] != "completed"]
    completed = [r for r in all_rows if r["status"] == "completed"]

    print(f"  Windows loaded  : {len(all_rows)} total ({run_mode} mode)")
    print(f"  Already done    : {len(completed)}")
    print(f"  To process      : {len(pending)}")
    return pending


def mark_window_completed(window_id: str):
    """
    Update status='completed' for a window in backfill_windows.csv.
    Rewrites the full file — safe, it's only 77 rows.
    """
    rows = []
    fieldnames = None
    with open(WINDOWS_CSV, newline="", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row["window_id"].strip() == window_id:
                row["status"] = "completed"
            rows.append(row)

    with open(WINDOWS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ─────────────────────────────────────────────
# BigQuery idempotency
# ─────────────────────────────────────────────
def already_in_bigquery(keyword_id: str, pub_after: date, pub_before: date) -> bool:
    """
    Check search_runs to see if this keyword × window was already collected.
    Second-layer idempotency — protects against CSV being out of sync.
    """
    query = f"""
        SELECT COUNT(*) AS cnt
        FROM `{TABLE_SEARCH_RUNS}`
        WHERE keyword_id       = @keyword_id
          AND published_after  = @published_after
          AND published_before = @published_before
          AND run_type         = 'backfill'
    """
    params = [
        bigquery.ScalarQueryParameter("keyword_id",       "STRING", keyword_id),
        bigquery.ScalarQueryParameter("published_after",  "DATE",   pub_after.isoformat()),
        bigquery.ScalarQueryParameter("published_before", "DATE",   pub_before.isoformat()),
    ]
    result = bq_client.query(
        query, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result()
    return next(iter(result)).cnt > 0


# ─────────────────────────────────────────────
# Cloud Storage
# ─────────────────────────────────────────────
def save_to_gcs(data: dict, keyword_id: str, pub_after: date, run_id: str):
    bucket = gcs_client.bucket(BUCKET_NAME)
    path   = f"{GCS_BACKFILL_PREFIX}/{keyword_id}/{pub_after.strftime('%Y-%m')}/{run_id}.json"
    blob   = bucket.blob(path)
    blob.upload_from_string(json.dumps(data, indent=2), content_type="application/json")
    print(f"    ✓ GCS → gs://{BUCKET_NAME}/{path}")


# ─────────────────────────────────────────────
# YouTube API calls
# ─────────────────────────────────────────────
def search_videos(keyword: str, pub_after: date, pub_before: date,
                  max_results: int, region: str, language: str):
    """Call search.list. Costs 100 units."""
    params = dict(
        part            = "id",
        q               = keyword,
        type            = "video",
        maxResults      = max_results,
        order           = "relevance",
        publishedAfter  = f"{pub_after.isoformat()}T00:00:00Z",
        publishedBefore = f"{pub_before.isoformat()}T23:59:59Z",
    )
    if region:
        params["regionCode"]        = region
    if language:
        params["relevanceLanguage"] = language

    response  = youtube.search().list(**params).execute()
    video_ids = [item["id"]["videoId"] for item in response.get("items", [])]
    return video_ids, response


def get_video_details(video_ids: list[str]) -> list[dict]:
    """Call videos.list. Costs 1 unit per video."""
    if not video_ids:
        return []
    response = youtube.videos().list(
        part       = "snippet,contentDetails,statistics",
        id         = ",".join(video_ids),
        maxResults = 50,
    ).execute()
    return response.get("items", [])


def get_channel_details(channel_ids: list[str]) -> list[dict]:
    """Call channels.list for deduplicated channel IDs. Costs 1 unit per channel."""
    if not channel_ids:
        return []
    response = youtube.channels().list(
        part       = "snippet,statistics",
        id         = ",".join(channel_ids),
        maxResults = 50,
    ).execute()
    return response.get("items", [])


# ─────────────────────────────────────────────
# BigQuery writes
# ─────────────────────────────────────────────
def upsert_videos(video_items: list[dict]):
    """MERGE video records — never creates duplicates."""
    if not video_items:
        return

    now  = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in video_items:
        s      = item.get("snippet", {})
        stats  = item.get("statistics", {})
        detail = item.get("contentDetails", {})
        rows.append({
            "video_id":      item["id"],
            "title":         s.get("title", ""),
            "channel_id":    s.get("channelId", ""),
            "published_at":  s.get("publishedAt", ""),
            "description":   s.get("description", "")[:500],
            "duration":      detail.get("duration", ""),
            "view_count":    int(stats.get("viewCount",    0) or 0),
            "like_count":    int(stats.get("likeCount",    0) or 0),
            "comment_count": int(stats.get("commentCount", 0) or 0),
            "last_updated":  now,
        })

    temp = f"{FULL_DATASET}._temp_videos_{uuid.uuid4().hex[:8]}"
    job_config = bigquery.LoadJobConfig(
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema = [
            bigquery.SchemaField("video_id",      "STRING"),
            bigquery.SchemaField("title",         "STRING"),
            bigquery.SchemaField("channel_id",    "STRING"),
            bigquery.SchemaField("published_at",  "TIMESTAMP"),
            bigquery.SchemaField("description",   "STRING"),
            bigquery.SchemaField("duration",      "STRING"),
            bigquery.SchemaField("view_count",    "INT64"),
            bigquery.SchemaField("like_count",    "INT64"),
            bigquery.SchemaField("comment_count", "INT64"),
            bigquery.SchemaField("last_updated",  "TIMESTAMP"),
        ],
    )
    bq_client.load_table_from_json(rows, temp, job_config=job_config).result()
    bq_client.query(f"""
        MERGE `{TABLE_VIDEOS}` T
        USING `{temp}` S ON T.video_id = S.video_id
        WHEN MATCHED THEN UPDATE SET
            T.title         = S.title,
            T.view_count    = S.view_count,
            T.like_count    = S.like_count,
            T.comment_count = S.comment_count,
            T.last_updated  = S.last_updated
        WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    bq_client.delete_table(temp)


def upsert_channels(channel_items: list[dict]):
    """MERGE channel records — never creates duplicates."""
    if not channel_items:
        return

    now  = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in channel_items:
        s     = item.get("snippet", {})
        stats = item.get("statistics", {})
        rows.append({
            "channel_id":       item["id"],
            "channel_title":    s.get("title", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
            "video_count":      int(stats.get("videoCount",      0) or 0),
            "last_updated":     now,
        })

    temp = f"{FULL_DATASET}._temp_channels_{uuid.uuid4().hex[:8]}"
    job_config = bigquery.LoadJobConfig(
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema = [
            bigquery.SchemaField("channel_id",       "STRING"),
            bigquery.SchemaField("channel_title",    "STRING"),
            bigquery.SchemaField("subscriber_count", "INT64"),
            bigquery.SchemaField("video_count",      "INT64"),
            bigquery.SchemaField("last_updated",     "TIMESTAMP"),
        ],
    )
    bq_client.load_table_from_json(rows, temp, job_config=job_config).result()
    bq_client.query(f"""
        MERGE `{TABLE_CHANNELS}` T
        USING `{temp}` S ON T.channel_id = S.channel_id
        WHEN MATCHED THEN UPDATE SET
            T.channel_title    = S.channel_title,
            T.subscriber_count = S.subscriber_count,
            T.video_count      = S.video_count,
            T.last_updated     = S.last_updated
        WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    bq_client.delete_table(temp)


def insert_search_run(run: dict):
    errors = bq_client.insert_rows_json(TABLE_SEARCH_RUNS, [run])
    if errors:
        raise RuntimeError(f"search_runs insert error: {errors}")


def insert_search_results(results: list[dict]):
    if not results:
        return
    errors = bq_client.insert_rows_json(TABLE_SEARCH_RESULTS, results)
    if errors:
        raise RuntimeError(f"search_results insert error: {errors}")


# ─────────────────────────────────────────────
# Core: one keyword × one window
# ─────────────────────────────────────────────
def process_window(kw: dict, window: dict, dry_run: bool) -> bool:
    """
    Run the full pipeline for one keyword × one window.
    Returns True if processed successfully (or legitimately skipped).
    Returns False if an error occurred — window stays pending in CSV for retry.
    """
    keyword_id  = kw["keyword_id"]
    keyword     = kw.get("search_string") or kw.get("keyword", "")
    max_results = int(kw.get("max_results", 50))
    region      = kw.get("region", "").strip()
    language    = kw.get("language", "en").strip()

    window_id  = window["window_id"]
    pub_after  = date.fromisoformat(window["published_after"])
    pub_before = date.fromisoformat(window["published_before"])

    if dry_run:
        print(f"  DRY RUN | {window_id} | {pub_after} → {pub_before} | "
              f"keyword={keyword_id} '{keyword}'")
        return True

    # ── Idempotency check ─────────────────────────────────────
    if already_in_bigquery(keyword_id, pub_after, pub_before):
        log_window_skip(window_id, window["published_after"],
                        keyword_id, keyword, reason="already_in_bigquery")
        return True

    log_window_start(window_id, window["published_after"],
                     window["published_before"], keyword_id, keyword)

    run_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc)

    try:
        # ── Step 1: YouTube search ────────────────────────────
        video_ids, search_response = search_videos(
            keyword, pub_after, pub_before, max_results, region, language
        )
        total_results = len(video_ids)

        if total_results == 0:
            log_zero_results(window_id, window["published_after"], keyword_id, keyword)
            insert_search_run({
                "search_run_id":    run_id,
                "keyword_id":       keyword_id,
                "keyword":          keyword,
                "published_after":  pub_after.isoformat(),
                "published_before": pub_before.isoformat(),
                "region":           region,
                "language":         language,
                "max_results":      max_results,
                "order_by":         "relevance",
                "total_results":    0,
                "run_type":         "backfill",
                "executed_at":      now.isoformat(),
            })
            return True

        # ── Step 2: Video details ─────────────────────────────
        video_items = get_video_details(video_ids)

        # ── Step 3: Channel details (deduplicated) ────────────
        channel_ids   = list({
            v.get("snippet", {}).get("channelId")
            for v in video_items
            if v.get("snippet", {}).get("channelId")
        })
        channel_items = get_channel_details(channel_ids)

        # ── Step 4: Save raw JSON to GCS ──────────────────────
        save_to_gcs(
            {
                "search_run_id":    run_id,
                "keyword_id":       keyword_id,
                "keyword":          keyword,
                "published_after":  pub_after.isoformat(),
                "published_before": pub_before.isoformat(),
                "executed_at":      now.isoformat(),
                "search_response":  search_response,
                "video_items":      video_items,
                "channel_items":    channel_items,
            },
            keyword_id, pub_after, run_id,
        )

        # ── Step 5: BigQuery writes ───────────────────────────
        upsert_videos(video_items)
        upsert_channels(channel_items)

        insert_search_run({
            "search_run_id":    run_id,
            "keyword_id":       keyword_id,
            "keyword":          keyword,
            "published_after":  pub_after.isoformat(),
            "published_before": pub_before.isoformat(),
            "region":           region,
            "language":         language,
            "max_results":      max_results,
            "order_by":         "relevance",
            "total_results":    total_results,
            "run_type":         "backfill",
            "executed_at":      now.isoformat(),
        })

        insert_search_results([
            {
                "search_run_id":   run_id,
                "video_id":        vid,
                "keyword_id":      keyword_id,
                "rank_in_results": rank,
                "collected_at":    now.isoformat(),
            }
            for rank, vid in enumerate(video_ids, start=1)
        ])

        # ── Step 6: Log success ───────────────────────────────
        log_window_complete(
            window_id, window["published_after"],
            keyword_id, keyword, total_results, len(channel_items)
        )

        time.sleep(0.5)
        return True

    except Exception as e:
        log_failure(
            step       = type(e).__name__,
            keyword_id = keyword_id,
            keyword    = keyword,
            window_id  = window_id,
            pub_after  = window["published_after"],
            error      = e,
        )
        return False


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="YouTube Reading Intelligence Dashboard — Historical Backfill"
    )
    parser.add_argument(
        "--run",
        choices=["demo", "full"],
        default="demo",
        help="'demo' = Jan 2025–May 2026 (priority=demo windows). "
             "'full' = all windows Jan 2020–May 2026.",
    )
    parser.add_argument(
        "--keyword_id",
        default=None,
        help="Limit to a single keyword_id (e.g. KW0004). Runs all if omitted.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Print the plan without calling any APIs or writing anything.",
    )
    args = parser.parse_args()

    keywords  = load_keywords(args.keyword_id)
    windows   = load_windows(args.run)
    quota_est = len(keywords) * len(windows) * 150

    log_run_start(
        script        = "backfill_search.py",
        mode          = args.run,
        keyword_count = len(keywords),
        window_count  = len(windows),
        quota_est     = quota_est,
        dry_run       = args.dry_run,
    )

    if quota_est > 10_000:
        print(f"\n  ⚠️  Estimated quota ({quota_est:,} units) exceeds daily limit (10,000).")
        print(f"      Run fewer keywords or split across days.\n")

    failed_labels   = []
    succeeded_count = 0

    for window in windows:
        window_id     = window["window_id"]
        window_errors = []

        for kw in keywords:
            success = process_window(kw, window, dry_run=args.dry_run)
            if not success:
                label = f"{window_id}/{kw['keyword_id']}"
                window_errors.append(label)
                failed_labels.append(label)

        if not args.dry_run:
            if not window_errors:
                mark_window_completed(window_id)
                succeeded_count += 1

    log_summary(
        total_windows = len(windows),
        succeeded     = succeeded_count,
        failed        = failed_labels,
        dry_run       = args.dry_run,
    )


if __name__ == "__main__":
    main()
