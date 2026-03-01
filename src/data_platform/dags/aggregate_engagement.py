"""DAG: Aggregate pageview engagement from BigQuery and sync to PG news_features."""

from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.models import Variable
    from airflow.hooks.base import BaseHook
except ImportError:
    pass


@dag(
    dag_id="aggregate_engagement",
    description="Aggregate portal pageviews from BigQuery and sync view_count to PG news_features",
    schedule="0 8 * * *",  # Daily at 8 AM UTC
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["gold", "features", "engagement"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
)
def aggregate_engagement_dag():

    @task()
    def aggregate_and_sync(**context):
        from data_platform.jobs.bigquery.engagement import (
            fetch_engagement_metrics,
            batch_upsert_engagement,
        )

        project_id = Variable.get("gcp_project_id")
        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

        metrics_df = fetch_engagement_metrics(project_id, days=30)
        if metrics_df.empty:
            return {"status": "no_data", "count": 0}

        count = batch_upsert_engagement(db_url, metrics_df)
        return {"status": "ok", "count": count}

    aggregate_and_sync()


dag_instance = aggregate_engagement_dag()
