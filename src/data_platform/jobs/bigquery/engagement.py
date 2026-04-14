"""Aggregate pageview engagement metrics from BigQuery."""

import json
import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

ENGAGEMENT_QUERY = """
    SELECT
        REGEXP_EXTRACT(url_path, r'/artigos/([a-z0-9][a-z0-9_-]+)') AS unique_id,
        COUNT(*) AS view_count,
        COUNT(DISTINCT session_id) AS unique_sessions
    FROM `{project_id}.dgb_gold.umami_pageviews`
    WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
      AND url_path LIKE '/artigos/%'
    GROUP BY 1
    HAVING unique_id IS NOT NULL
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
    engine = create_engine(db_url, poolclass=NullPool)
    upsert_sql = text("""
        INSERT INTO news_features (unique_id, features)
        VALUES (:uid, :features)
        ON CONFLICT (unique_id) DO UPDATE
        SET features = news_features.features || :features,
            updated_at = NOW()
    """)
    count = 0
    try:
        with engine.begin() as conn:
            all_ids = metrics_df["unique_id"].tolist()
            if all_ids:
                valid_result = conn.execute(
                    text("SELECT unique_id FROM news WHERE unique_id = ANY(:ids)"),
                    {"ids": all_ids},
                )
                valid_ids = set(valid_result.scalars().all())
                initial_count = len(metrics_df)
                metrics_df = metrics_df[metrics_df["unique_id"].isin(valid_ids)]
                orphaned = initial_count - len(metrics_df)
                if orphaned:
                    logger.warning(
                        f"Filtered {orphaned} orphaned unique_ids not found in news table"
                    )
            for _, row in metrics_df.iterrows():
                features = json.dumps({
                    "view_count": int(row["view_count"]),
                    "unique_sessions": int(row["unique_sessions"]),
                })
                conn.execute(upsert_sql, {"uid": row["unique_id"], "features": features})
                count += 1
        logger.info(f"Upserted engagement metrics for {count} articles")
    finally:
        engine.dispose()
    return count
