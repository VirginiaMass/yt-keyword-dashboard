import os
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from googleapiclient.discovery import build
from upload_to_gcs import upload_json_to_gcs

# Load API key from .env
load_dotenv()
API_KEY = os.getenv("YOUTUBE_API_KEY")

# Build YouTube client
youtube = build("youtube", "v3", developerKey=API_KEY)

#Load keywords from config file and build params
def load_keywords(filepath="config/keywords.csv"):
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()  # remove spaces from column names
    df = df.map(lambda x: x.strip() if isinstance(x, str) else x)  # remove spaces from data
    return df

def build_search_params(keyword, region, language, max_results, date_range_days):
    published_after = (
            datetime.now(timezone.utc) - timedelta(days=int(date_range_days))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "q": keyword,
        "part": "id,snippet",
        "type": "video",
        "maxResults": int(max_results),
        "order": "date",
        "publishedAfter": published_after
    }

    # Only add region if it's specified
    if pd.notna(region) and region != "":
        params["regionCode"] = region

    # Only add language if it's specified
    if pd.notna(language) and language != "":
        params["relevanceLanguage"] = language

    return params

def search_videos(params):
    request = youtube.search().list(**params)
    response = request.execute()
    return response

def get_video_stats(video_ids):
    request = youtube.videos().list(
        part="statistics,contentDetails,snippet",
        id=",".join(video_ids)
    )
    response = request.execute()
    return response

def fetch_all_keywords():
    keywords_df = load_keywords()
    all_results = {}

    for _, row in keywords_df.iterrows():
        keyword = row["keyword"]
        region = row["region"]
        language = row["language"]
        max_results = row["max_results"]
        date_range_days = row["date_range_days"]

        print(f"\nFetching: '{keyword}' | region: {region} | last {date_range_days} days")

        params = build_search_params(keyword, region, language, max_results, date_range_days)
        search_results = search_videos(params)

        video_ids = [
            item["id"]["videoId"]
            for item in search_results.get("items", [])
        ]

        if not video_ids:
            print(f"  No videos found for '{keyword}'")
            continue

        print(f"  Found {len(video_ids)} videos")

        # Get stats for those videos
        stats = get_video_stats(video_ids)
        all_results[keyword] = stats

        # Upload raw JSON to Cloud Storage
        upload_json_to_gcs(stats, keyword)

    return all_results

if __name__ == "__main__":
    results = fetch_all_keywords()

    # Print a sample of the results
    for keyword, data in results.items():
        print(f"\n--- {keyword} ---")
        for item in data.get("items", []):
            title = item["snippet"]["title"]
            views = item["statistics"].get("viewCount", "N/A")
            print(f"  {title} | views: {views}")