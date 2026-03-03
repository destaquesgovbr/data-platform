"""
DAG: Sync Umami Analytics → BigQuery.

Schedule: Daily at 9 AM UTC (after sync_pg_to_bigquery at 7 AM and aggregate_engagement at 8 AM).
Reads pageviews and custom events from Umami's PostgreSQL database and loads
into BigQuery Gold layer tables (umami_pageviews, umami_events).
"""

import logging
from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.models import Variable
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dag(
    dag_id="sync_umami_to_bigquery",
    description="Sync Umami pageviews and custom events from PostgreSQL to BigQuery",
    schedule="0 9 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["data-platform", "bigquery", "umami", "analytics"],
    default_args={
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Sync Umami Analytics → BigQuery

    Reads pageview events and custom events from the Umami PostgreSQL database
    (`umami` database on the same Cloud SQL instance) and loads them into
    BigQuery tables:

    - `dgb_gold.umami_pageviews` — pageviews enriched with session data
    - `dgb_gold.umami_events` — custom events with event_data JSON

    **Connection**: Uses Airflow connection `umami_postgres` (user `umami_app`).

    **Schedule**: Daily at 9 AM UTC, syncs previous day's data.
    """,
)
def sync_umami_to_bigquery():

    @task()
    def sync_pageviews(**context):
        """Extract pageviews from Umami and load to BigQuery."""
        from data_platform.jobs.bigquery.umami_sync import (
            fetch_umami_pageviews,
            get_umami_db_url,
            load_to_bigquery,
            PAGEVIEWS_SCHEMA,
        )

        db_url = get_umami_db_url()
        project_id = Variable.get("gcp_project_id", default_var="inspire-7-finep")

        # Date range: previous day (UTC)
        logical_date = context.get("logical_date") or context.get("execution_date")
        if logical_date is None:
            logical_date = datetime.utcnow()

        start_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = logical_date.strftime("%Y-%m-%d")

        df = fetch_umami_pageviews(db_url, start_date, end_date)
        if df.empty:
            return {"status": "no_data", "date": start_date, "rows": 0}

        rows = load_to_bigquery(
            df, project_id, "dgb_gold.umami_pageviews", PAGEVIEWS_SCHEMA
        )
        return {"status": "ok", "date": start_date, "rows": rows}

    @task()
    def sync_events(**context):
        """Extract custom events from Umami and load to BigQuery."""
        from data_platform.jobs.bigquery.umami_sync import (
            fetch_umami_events,
            get_umami_db_url,
            load_to_bigquery,
            EVENTS_SCHEMA,
        )

        db_url = get_umami_db_url()
        project_id = Variable.get("gcp_project_id", default_var="inspire-7-finep")

        # Date range: previous day (UTC)
        logical_date = context.get("logical_date") or context.get("execution_date")
        if logical_date is None:
            logical_date = datetime.utcnow()

        start_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = logical_date.strftime("%Y-%m-%d")

        df = fetch_umami_events(db_url, start_date, end_date)
        if df.empty:
            return {"status": "no_data", "date": start_date, "rows": 0}

        rows = load_to_bigquery(
            df, project_id, "dgb_gold.umami_events", EVENTS_SCHEMA
        )
        return {"status": "ok", "date": start_date, "rows": rows}

    # Tasks run in parallel (pageviews and events are independent)
    sync_pageviews()
    sync_events()


dag_instance = sync_umami_to_bigquery()
