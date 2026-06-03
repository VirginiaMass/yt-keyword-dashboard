# config/constants.py
# ============================================================
# Central reference for all project-level constants.
# Every ETL script imports from here — never hardcode these
# values directly in scripts.
#
# If anything changes (dataset name, bucket name, region),
# change it here and it propagates everywhere.
# ============================================================

# ── GCP Project ─────────────────────────────────────────────
PROJECT_ID       = "portolioprojects"
REGION           = "us-central1"

# ── BigQuery ─────────────────────────────────────────────────
DATASET_ID       = "yt_dashboard"
FULL_DATASET     = f"{PROJECT_ID}.{DATASET_ID}"

# ── Cloud Storage ────────────────────────────────────────────
BUCKET_NAME      = "yt-keyword-dashboard-raw"
GCS_BACKFILL_PREFIX  = "backfill"
GCS_DAILY_PREFIX     = "daily"

# ── YouTube API ──────────────────────────────────────────────
YOUTUBE_API_VERSION  = "v3"
MAX_RESULTS_DEFAULT  = 50

# ── Config file paths (relative to repo root) ────────────────
KEYWORDS_CSV     = "config/keywords.csv"
REGISTRY_CSV     = "config/keyword_registry.csv"
WINDOWS_CSV      = "config/backfill_windows.csv"

# ── BigQuery table names ─────────────────────────────────────
TABLE_SEARCH_RUNS        = f"{FULL_DATASET}.search_runs"
TABLE_SEARCH_RESULTS     = f"{FULL_DATASET}.search_results"
TABLE_VIDEOS             = f"{FULL_DATASET}.videos"
TABLE_CHANNELS           = f"{FULL_DATASET}.channels"
TABLE_DAILY_SNAPSHOTS    = f"{FULL_DATASET}.video_daily_snapshots"
TABLE_KEYWORD_REGISTRY   = f"{FULL_DATASET}.keyword_registry"
TABLE_TRANSCRIPTS        = f"{FULL_DATASET}.transcripts"
TABLE_TOPIC_ASSIGNMENTS  = f"{FULL_DATASET}.topic_assignments"
