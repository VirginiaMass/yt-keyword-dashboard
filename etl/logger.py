import logging
import os
from datetime import datetime, timezone

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Create a log filename with today's date
log_filename = f"logs/pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"

# Set up the logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(log_filename),   # saves to file
        logging.StreamHandler()              # also prints to terminal
    ]
)

logger = logging.getLogger(__name__)

def log_failure(step, keyword, error):
    logger.error(f"FAILURE | step={step} | keyword='{keyword}' | error={str(error)}")

def log_summary(total, succeeded, failed_keywords):
    logger.info("=" * 60)
    logger.info(f"PIPELINE SUMMARY | total={total} | succeeded={succeeded} | failed={len(failed_keywords)}")
    if failed_keywords:
        logger.warning(f"FAILED KEYWORDS | {', '.join(failed_keywords)}")
    logger.info("=" * 60)