import os
import json
from datetime import datetime, timezone
from google.cloud import storage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get credentials
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

# Your bucket name
BUCKET_NAME = "yt-keyword-dashboard-raw"


def upload_json_to_gcs(data, keyword, bucket_name=BUCKET_NAME):

    # Create a storage client
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Create a filename with keyword and timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_keyword = keyword.replace(" ", "_").lower()
    filename = f"youtube/raw/{safe_keyword}/{timestamp}.json"

    # Upload
    blob = bucket.blob(filename)
    blob.upload_from_string(
        json.dumps(data, indent=2),
        content_type="application/json"
    )

    print(f"  Uploaded to gs://{bucket_name}/{filename}")
    return filename


if __name__ == "__main__":
    # Test with dummy data
    test_data = {"test": "hello from pipeline"}
    upload_json_to_gcs(test_data, "test keyword")