"""DAG: Compute similar article clusters using pgvector cosine similarity."""

from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.hooks.base import BaseHook
except ImportError:
    pass


@dag(
    dag_id="compute_clusters",
    description="Find similar articles using pgvector embeddings and store in news_features",
    schedule="30 7 * * *",  # Daily at 7:30 AM UTC (after BigQuery sync at 7 AM)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["silver", "features", "similarity"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
)
def compute_clusters_dag():

    @task()
    def find_and_store_clusters(**context):
        """Find similar articles and upsert to news_features."""
        from data_platform.jobs.similarity.clusters import (
            fetch_similar_articles,
            group_similar_articles,
            batch_upsert_clusters,
        )

        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

        similarities_df = fetch_similar_articles(db_url, lookback_days=1)
        if similarities_df.empty:
            return {"status": "no_data", "count": 0}

        clusters = group_similar_articles(similarities_df)
        count = batch_upsert_clusters(db_url, clusters)
        return {"status": "ok", "articles_clustered": count}

    find_and_store_clusters()


dag_instance = compute_clusters_dag()
