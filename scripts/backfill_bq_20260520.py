#!/usr/bin/env python3
"""
One-time backfill: BigQuery fato_noticias for 2026-05-11 to 2026-05-20.

Backfills 9 days of missed data caused by schema mismatch (content_hash column
was added to the code but not to the BigQuery table).

Prerequisites:
  - ALTER TABLE applied (content_hash column exists in BigQuery)
  - Environment variables: DATABASE_URL, GCP_PROJECT_ID, DATA_LAKE_BUCKET

Usage:
    DATABASE_URL=... poetry run python scripts/backfill_bq_20260520.py
"""

import logging
import os
import sys
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    project_id = os.environ.get("GCP_PROJECT_ID", "inspire-7-finep")
    bucket = os.environ.get("DATA_LAKE_BUCKET", "inspire-7-finep-dgb-data-lake")

    from data_platform.jobs.bigquery.sync_to_bigquery import (
        fetch_news_for_bigquery,
        load_parquet_to_bigquery,
        write_to_parquet_gcs,
    )

    start = date(2026, 5, 11)
    end = date(2026, 5, 20)
    current = start
    total_rows = 0

    logger.info(f"Backfilling BigQuery fato_noticias: {start} to {end}")
    logger.info(f"Project: {project_id} | Bucket: {bucket}")

    while current < end:
        next_day = current + timedelta(days=1)
        df = fetch_news_for_bigquery(db_url, str(current), str(next_day))
        if not df.empty:
            gcs_uri = write_to_parquet_gcs(df, bucket, str(current))
            rows = load_parquet_to_bigquery(gcs_uri, project_id)
            total_rows += rows
            logger.info(f"  {current}: {rows} rows loaded")
        else:
            logger.info(f"  {current}: no data")
        current = next_day

    logger.info(f"Backfill complete: {total_rows} total rows loaded across {(end - start).days} days")


if __name__ == "__main__":
    main()
