"""
create_schema.py
Run once to create all BigQuery tables for the YouTube Reading Intelligence Dashboard.
Safe to re-run — uses CREATE TABLE IF NOT EXISTS via the BQ client.

Usage (from repo root):
    python etl/create_schema.py

Requirements:
    pip install google-cloud-bigquery python-dotenv
"""

import sys
import os
sys.path.insert(0, ".")

from dotenv import load_dotenv
from google.cloud import bigquery
from config.constants import PROJECT_ID, REGION, FULL_DATASET

load_dotenv()

client = bigquery.Client(project=PROJECT_ID, location=REGION)


def run_ddl(sql: str, label: str):
    print(f"  Creating {label}...", end=" ")
    client.query(sql).result()
    print("✓")


def main():
    print(f"\n=== Creating BigQuery schema in {FULL_DATASET} ===\n")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.search_runs` (
            search_run_id   STRING    NOT NULL,
            keyword_id      STRING    NOT NULL,
            keyword         STRING    NOT NULL,
            published_after DATE,
            published_before DATE,
            region          STRING,
            language        STRING,
            max_results     INTEGER,
            order_by        STRING,
            total_results   INTEGER,
            run_type        STRING    NOT NULL,
            executed_at     TIMESTAMP NOT NULL
        )
    """, "search_runs")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.search_results` (
            search_run_id   STRING    NOT NULL,
            video_id        STRING    NOT NULL,
            keyword_id      STRING    NOT NULL,
            rank_in_results INTEGER,
            collected_at    TIMESTAMP NOT NULL
        )
    """, "search_results")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.videos` (
            video_id        STRING    NOT NULL,
            title           STRING,
            channel_id      STRING,
            published_at    TIMESTAMP,
            description     STRING,
            duration        STRING,
            view_count      INT64,
            like_count      INT64,
            comment_count   INT64,
            last_updated    TIMESTAMP
        )
    """, "videos")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.channels` (
            channel_id      STRING    NOT NULL,
            channel_title   STRING,
            subscriber_count INT64,
            video_count     INT64,
            last_updated    TIMESTAMP
        )
    """, "channels")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.video_daily_snapshots` (
            snapshot_date   DATE      NOT NULL,
            video_id        STRING    NOT NULL,
            view_count      INT64,
            like_count      INT64,
            comment_count   INT64,
            collected_at    TIMESTAMP NOT NULL
        )
    """, "video_daily_snapshots")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.keyword_registry` (
            keyword_id      STRING    NOT NULL,
            keyword         STRING    NOT NULL,
            category        STRING,
            subcategory     STRING,
            keyword_type    STRING,
            priority        STRING,
            notes           STRING
        )
    """, "keyword_registry")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.transcripts` (
            video_id        STRING    NOT NULL,
            transcript_text STRING,
            language        STRING,
            collected_at    TIMESTAMP NOT NULL
        )
    """, "transcripts")

    run_ddl(f"""
        CREATE TABLE IF NOT EXISTS `{FULL_DATASET}.topic_assignments` (
            video_id        STRING    NOT NULL,
            topic_id        STRING,
            topic_label     STRING,
            confidence_score FLOAT64,
            model_used      STRING,
            assigned_at     TIMESTAMP NOT NULL
        )
    """, "topic_assignments")

    print("\n=== All tables created successfully ===\n")
    print("Next step: load keyword_registry.csv into BigQuery.")
    print("  python etl/load_keyword_registry.py\n")


if __name__ == "__main__":
    main()
