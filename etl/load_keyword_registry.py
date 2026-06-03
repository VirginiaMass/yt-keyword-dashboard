"""
load_keyword_registry.py
Loads config/keyword_registry.csv into BigQuery table keyword_registry.
Uses WRITE_TRUNCATE so it's always in sync with the CSV.

Usage (from repo root):
    python etl/load_keyword_registry.py

Run this whenever you add or update keywords in keyword_registry.csv.
"""

import sys
sys.path.insert(0, ".")

import csv
from dotenv import load_dotenv
from google.cloud import bigquery
from config.constants import PROJECT_ID, REGION, REGISTRY_CSV, TABLE_KEYWORD_REGISTRY

load_dotenv()


def main():
    client = bigquery.Client(project=PROJECT_ID, location=REGION)

    with open(REGISTRY_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            {
                "keyword_id":   row["keyword_id"].strip(),
                "keyword":      row["keyword"].strip(),
                "category":     row["category"].strip(),
                "subcategory":  row["subcategory"].strip(),
                "keyword_type": row["keyword_type"].strip(),
                "priority":     row["priority"].strip(),
                "notes":        row.get("notes", "").strip(),
            }
            for row in reader
        ]

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[
            bigquery.SchemaField("keyword_id",   "STRING"),
            bigquery.SchemaField("keyword",      "STRING"),
            bigquery.SchemaField("category",     "STRING"),
            bigquery.SchemaField("subcategory",  "STRING"),
            bigquery.SchemaField("keyword_type", "STRING"),
            bigquery.SchemaField("priority",     "STRING"),
            bigquery.SchemaField("notes",        "STRING"),
        ],
    )

    job = client.load_table_from_json(rows, TABLE_KEYWORD_REGISTRY, job_config=job_config)
    job.result()

    print(f"✓ Loaded {len(rows)} keywords into {TABLE_KEYWORD_REGISTRY}")
    active = [r for r in rows if r.get("priority")]
    for r in rows:
        print(f"  {r['keyword_id']}  {r['keyword']:<25} [{r['category']} / {r['subcategory']}]")


if __name__ == "__main__":
    main()
