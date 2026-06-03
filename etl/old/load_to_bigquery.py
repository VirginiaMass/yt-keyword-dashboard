import os
import json
from google.cloud import storage, bigquery
from dotenv import load_dotenv
from logger import log_failure, log_summary

# Load environment variables
load_dotenv()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Constants
BUCKET_NAME = "yt-keyword-dashboard-raw"
PROJECT_ID = "portolioprojects"
DATASET_ID = "yt_dashboard"

# BigQuery client
bq_client = bigquery.Client(project=PROJECT_ID)
gcs_client = storage.Client()

#List all JSON files in Cloud Storage bucket
def list_new_files(bucket_name):
    bucket = gcs_client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix="youtube/raw/")
    return [blob.name for blob in blobs if blob.name.endswith(".json")]

def read_json_from_gcs(bucket_name, filename):
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(filename)
    content = blob.download_as_text()
    return json.loads(content)


def parse_videos(data, keyword):
    """Parse raw YouTube API response into a flat list of video records."""
    rows = []
    for item in data.get("items", []):
        try:
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            row = {
                "video_id": item.get("id"),
                "keyword": keyword,
                "title": snippet.get("title"),
                "channel_id": snippet.get("channelId"),
                "channel_title": snippet.get("channelTitle"),
                "published_at": snippet.get("publishedAt"),
                "description": snippet.get("description", "")[:500],
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration": content.get("duration"),
                "fetched_at": snippet.get("publishedAt")
            }
            rows.append(row)
        except Exception as e:
            log_failure("parse", keyword, e)
            continue
    return rows


def load_to_bigquery(rows, table_id):
    """Load a list of rows into a BigQuery table."""
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_id}"

    errors = bq_client.insert_rows_json(table_ref, rows)
    if errors:
        raise Exception(f"BigQuery insert errors: {errors}")

    print(f"  Loaded {len(rows)} rows into {table_ref}")


def create_videos_table():
    """Create the videos table in BigQuery if it doesn't exist."""
    schema = [
        bigquery.SchemaField("video_id", "STRING"),
        bigquery.SchemaField("keyword", "STRING"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("channel_id", "STRING"),
        bigquery.SchemaField("channel_title", "STRING"),
        bigquery.SchemaField("published_at", "TIMESTAMP"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("view_count", "INTEGER"),
        bigquery.SchemaField("like_count", "INTEGER"),
        bigquery.SchemaField("comment_count", "INTEGER"),
        bigquery.SchemaField("duration", "STRING"),
        bigquery.SchemaField("fetched_at", "TIMESTAMP"),
    ]

    table_ref = f"{PROJECT_ID}.{DATASET_ID}.videos"
    table = bigquery.Table(table_ref, schema=schema)

    try:
        bq_client.create_table(table)
        print(f"  Created table {table_ref}")
    except Exception:
        print(f"  Table {table_ref} already exists, skipping creation")


def run():
    """Main function — reads all files from GCS and loads into BigQuery."""
    print("Creating tables if needed...")
    create_videos_table()

    print("\nListing files in Cloud Storage...")
    files = list_new_files(BUCKET_NAME)
    print(f"Found {len(files)} files")

    failed = []
    succeeded = 0

    for filename in files:
        # Extract keyword from filename path
        # Path format: youtube/raw/{keyword}/{timestamp}.json
        parts = filename.split("/")
        keyword = parts[2].replace("_", " ")

        print(f"\nProcessing: {filename}")

        try:
            # Read raw JSON
            data = read_json_from_gcs(BUCKET_NAME, filename)

            # Parse into rows
            rows = parse_videos(data, keyword)

            if not rows:
                print(f"  No rows parsed for {keyword}")
                continue

            # Load to BigQuery
            load_to_bigquery(rows, "videos")
            succeeded += 1

        except Exception as e:
            log_failure("load", keyword, e)
            failed.append(keyword)
            continue

    log_summary(len(files), succeeded, failed)


if __name__ == "__main__":
    run()