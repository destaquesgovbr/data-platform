"""DAG: Compute similar article clusters using pgvector cosine similarity."""

import os
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
        """Find similar articles and upsert to news_features.

        Uses GraphQL API when GRAPHQL_API_URL is set, otherwise falls back
        to direct PostgreSQL queries via pgvector.
        """
        from data_platform.jobs.similarity.clusters import (
            group_similar_articles,
        )

        graphql_url = os.environ.get("GRAPHQL_API_URL")

        if graphql_url:
            return _run_via_graphql(graphql_url)
        else:
            return _run_via_postgres()

    def _run_via_graphql(graphql_url: str) -> dict:
        """Execute cluster computation via GraphQL API."""
        from data_platform.clients.graphql_client import GraphQLClient
        from data_platform.jobs.similarity.clusters import (
            batch_upsert_clusters_via_graphql,
            fetch_similar_articles_via_graphql,
            group_similar_articles,
        )

        # Fetch recent article IDs from GraphQL to know which ones to check
        # We reuse the similarity query which handles lookback internally
        with GraphQLClient(url=graphql_url) as gql_client:
            # First get recent article IDs via a lightweight query
            # The similarArticles query handles lookback on the server side,
            # so we need the list of recent unique_ids.
            # For now, we use the PG connection to get the ID list, then
            # GraphQL for similarity + upsert. In a full migration, the
            # ID list would also come from GraphQL.
            pg_conn = BaseHook.get_connection("postgres_default")
            db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

            from sqlalchemy import create_engine, text
            from sqlalchemy.pool import NullPool

            engine = create_engine(db_url, poolclass=NullPool)
            try:
                with engine.connect() as conn:
                    result = conn.execute(
                        text(
                            "SELECT unique_id FROM news "
                            "WHERE published_at >= NOW() - INTERVAL '1 day' "
                            "AND content_embedding IS NOT NULL"
                        )
                    )
                    unique_ids = [row[0] for row in result]
            finally:
                engine.dispose()

            if not unique_ids:
                return {"status": "no_data", "count": 0, "backend": "graphql"}

            similarities_df = fetch_similar_articles_via_graphql(gql_client, unique_ids)
            if similarities_df.empty:
                return {"status": "no_data", "count": 0, "backend": "graphql"}

            clusters = group_similar_articles(similarities_df)
            count = batch_upsert_clusters_via_graphql(gql_client, clusters)
            return {"status": "ok", "articles_clustered": count, "backend": "graphql"}

    def _run_via_postgres() -> dict:
        """Execute cluster computation via direct PostgreSQL queries."""
        from data_platform.jobs.similarity.clusters import (
            batch_upsert_clusters,
            fetch_similar_articles,
            group_similar_articles,
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
