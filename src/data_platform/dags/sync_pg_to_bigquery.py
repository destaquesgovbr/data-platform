"""
DAG: Sync PostgreSQL -> BigQuery (incremental daily).

Schedule: Daily at 7 AM UTC (after HuggingFace sync at 6 AM).
Syncs news + features from previous day into BigQuery Gold layer.
"""

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook
from airflow.models import Variable

logger = logging.getLogger(__name__)


@dag(
    dag_id="sync_pg_to_bigquery",
    schedule="0 7 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["data-platform", "bigquery", "gold"],
    default_args={
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Sync PostgreSQL -> BigQuery

    Incrementally syncs news articles and computed features from PostgreSQL
    to BigQuery `dgb_gold.fato_noticias` table.

    **Flow**: PG query -> Parquet (GCS) -> BigQuery LOAD JOB

    Also syncs dimension tables (agencies, themes) on each run.
    """,
)
def sync_pg_to_bigquery():

    @task
    def sync_facts(**context):
        """Query PG for previous day's news + features, load into BigQuery."""
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery,
            load_parquet_to_bigquery,
            write_to_parquet_gcs,
        )

        # Date range: previous day
        logical_date = context.get("logical_date") or context.get("execution_date")
        if logical_date is None:
            logical_date = datetime.utcnow()

        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = logical_date.strftime("%Y-%m-%d")

        # Get config
        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri()
        project_id = Variable.get("gcp_project_id", default_var="inspire-7-finep")
        bucket_name = Variable.get("data_lake_bucket", default_var="inspire-7-finep-dgb-data-lake")

        # 1. Fetch from PG
        df = fetch_news_for_bigquery(db_url, target_date, end_date)

        if df.empty:
            logger.info(f"No data for {target_date}, skipping")
            return {"status": "empty", "date": target_date, "rows": 0}

        # 2. Write Parquet to GCS
        gcs_uri = write_to_parquet_gcs(df, bucket_name, target_date)

        # 3. Load into BigQuery
        rows_loaded = load_parquet_to_bigquery(gcs_uri, project_id)

        return {"status": "success", "date": target_date, "rows": rows_loaded}

    @task
    def sync_dims(**context):
        """Sync dimension tables (agencies, themes) to BigQuery."""
        from data_platform.jobs.bigquery.sync_to_bigquery import sync_dimensions

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri()
        project_id = Variable.get("gcp_project_id", default_var="inspire-7-finep")

        sync_dimensions(db_url, project_id)
        return {"status": "success"}

    # Tasks run in parallel (no dependency between facts and dims)
    sync_facts()
    sync_dims()


dag_instance = sync_pg_to_bigquery()
