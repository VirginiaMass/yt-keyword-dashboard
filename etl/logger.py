"""
logger.py
Centralised logging for the YouTube Reading Intelligence Dashboard pipeline.

Writes to:
  - logs/pipeline_YYYYMMDD.log  (file, persists)
  - terminal (stdout, real-time)

Log levels used:
  INFO    — normal progress: session start, window complete, session end
  WARNING — unexpected but recoverable: 0 results, window skipped
  ERROR   — step failed, window stays pending, needs attention

Usage:
    from etl.logger import log_run_start, log_window_complete, log_window_skip,
                           log_failure, log_summary
"""

import logging
import os
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# Setup — runs once on import
# ─────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

log_filename = f"logs/pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("yt_dashboard")


# ─────────────────────────────────────────────
# Session-level events
# ─────────────────────────────────────────────
def log_run_start(script: str, mode: str, keyword_count: int,
                  window_count: int, quota_est: int, dry_run: bool):
    """
    Log the start of a pipeline session.
    Call this once at the top of main() before any API calls.
    """
    dry = "  [DRY RUN]" if dry_run else ""
    logger.info("=" * 60)
    logger.info(f"PIPELINE START{dry} | script={script} | mode={mode} | "
                f"keywords={keyword_count} | windows={window_count} | "
                f"quota_est=~{quota_est:,} units")
    logger.info("=" * 60)


def log_summary(total_windows: int, succeeded: int, failed: list[str], dry_run: bool):
    """
    Log the end-of-session summary.
    Call this once at the end of main() after all windows are processed.
    failed = list of human-readable labels for failed window/keyword pairs.
    """
    logger.info("=" * 60)
    if dry_run:
        logger.info(f"PIPELINE DRY RUN COMPLETE | windows_planned={total_windows}")
    else:
        logger.info(f"PIPELINE COMPLETE | total_windows={total_windows} | "
                    f"succeeded={succeeded} | failed={len(failed)}")
        if failed:
            logger.warning(f"FAILED (will retry on next run) | {' | '.join(failed)}")
        else:
            logger.info("All windows completed successfully.")
    logger.info("=" * 60)


# ─────────────────────────────────────────────
# Window-level events
# ─────────────────────────────────────────────
def log_window_start(window_id: str, pub_after: str, pub_before: str, keyword_id: str, keyword: str):
    """Log the start of processing for one keyword × window pair."""
    logger.info(f"WINDOW START | {window_id} | {pub_after} → {pub_before} | "
                f"keyword={keyword_id} '{keyword}'")


def log_window_complete(window_id: str, pub_after: str, keyword_id: str,
                        keyword: str, video_count: int, channel_count: int):
    """Log successful completion of one keyword × window pair."""
    logger.info(f"WINDOW COMPLETE | {window_id} | {pub_after[:7]} | "
                f"keyword={keyword_id} '{keyword}' | "
                f"videos={video_count} | channels={channel_count}")


def log_window_skip(window_id: str, pub_after: str, keyword_id: str, keyword: str, reason: str):
    """
    Log a skipped window.
    reason examples: 'already_in_bigquery', 'status=completed_in_csv'
    Use WARNING so skips are visible but don't look like errors.
    """
    logger.warning(f"WINDOW SKIP | {window_id} | {pub_after[:7]} | "
                   f"keyword={keyword_id} '{keyword}' | reason={reason}")


def log_zero_results(window_id: str, pub_after: str, keyword_id: str, keyword: str):
    """
    Log when a search returned 0 videos.
    This is valid (keyword may not have had activity that month) but worth tracking.
    """
    logger.warning(f"ZERO RESULTS | {window_id} | {pub_after[:7]} | "
                   f"keyword={keyword_id} '{keyword}' | "
                   f"no videos found for this window")


# ─────────────────────────────────────────────
# Failure events
# ─────────────────────────────────────────────
def log_failure(step: str, keyword_id: str, keyword: str,
                window_id: str, pub_after: str, error: Exception):
    """
    Log a pipeline step failure.
    step examples: 'search_videos', 'upsert_videos', 'insert_search_run', 'save_to_gcs'
    The window will stay 'pending' in backfill_windows.csv and retry on next run.
    """
    logger.error(f"FAILURE | step={step} | {window_id} | {pub_after[:7]} | "
                 f"keyword={keyword_id} '{keyword}' | error={type(error).__name__}: {error}")
