"""Aggregate pageview engagement metrics from BigQuery."""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

ENGAGEMENT_QUERY = """
    SELECT
        unique_id,
        COUNT(*) AS view_count,
        COUNT(DISTINCT session_id) AS unique_sessions
    FROM `{project_id}.dgb_gold.pageviews`
    WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY unique_id
    HAVING COUNT(*) > 0
    ORDER BY view_count DESC
"""


def fetch_engagement_metrics(project_id: str, days: int = 30) -> pd.DataFrame:
    """Query BigQuery for aggregated pageview metrics.

    Args:
        project_id: GCP project ID
        days: Number of days to aggregate

    Returns:
        DataFrame with columns [unique_id, view_count, unique_sessions]
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    query = ENGAGEMENT_QUERY.format(project_id=project_id, days=days)
    df = client.query(query).to_dataframe()
    logger.info(f"Fetched engagement metrics for {len(df)} articles")
    return df


def batch_upsert_engagement(db_url: str, metrics_df: pd.DataFrame) -> int:
    """Batch upsert view_count and unique_sessions into news_features.

    Args:
        db_url: PostgreSQL connection string
        metrics_df: DataFrame with [unique_id, view_count, unique_sessions]

    Returns:
        Number of rows updated
    """
    from data_platform.managers.postgres_manager import PostgresManager

    pg = PostgresManager(db_url=db_url, max_connections=2)
    count = 0
    try:
        for _, row in metrics_df.iterrows():
            features = {
                "view_count": int(row["view_count"]),
                "unique_sessions": int(row["unique_sessions"]),
            }
            if pg.upsert_features(row["unique_id"], features):
                count += 1
        logger.info(f"Upserted engagement metrics for {count} articles")
    finally:
        pg.close_all()
    return count
