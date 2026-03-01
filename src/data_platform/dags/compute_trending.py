"""
DAG: Compute trending scores from BigQuery and sync back to PostgreSQL.

Schedule: Every 6 hours.
Queries BigQuery fato_noticias for theme-based trending scores
and upserts them into PG news_features JSONB store.
"""

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook
from airflow.models import Variable

logger = logging.getLogger(__name__)


@dag(
    dag_id="compute_trending",
    description="Compute trending scores from BigQuery fato_noticias and sync back to PG news_features",
    schedule="0 */6 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["gold", "features", "trending"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Compute Trending Scores

    Queries BigQuery `dgb_gold.fato_noticias` to compute per-article trending
    scores (24h volume vs 7-day average for each theme), then upserts results
    back into PostgreSQL `news_features.features` JSONB.

    **Flow**: BigQuery query -> DataFrame -> PG upsert (news_features)
    """,
)
def compute_trending_dag():

    @task()
    def compute_and_sync_trending(**context):
        """Fetch trending from BQ and upsert to PG."""
        from data_platform.jobs.bigquery.trending import (
            batch_upsert_trending,
            fetch_trending_scores,
        )

        project_id = Variable.get("gcp_project_id", default_var="inspire-7-finep")
        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri()

        scores_df = fetch_trending_scores(project_id)
        if len(scores_df) == 0:
            logger.info("No trending scores returned from BigQuery, skipping")
            return {"status": "no_data", "count": 0}

        count = batch_upsert_trending(db_url, scores_df)
        return {"status": "ok", "count": count}

    compute_and_sync_trending()


dag_instance = compute_trending_dag()
