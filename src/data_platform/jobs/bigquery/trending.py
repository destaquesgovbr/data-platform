"""Compute trending scores from BigQuery fato_noticias."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# BigQuery trending score query
# Calculates articles per theme in last 24h vs 7d average.
# Higher score = theme is trending (more articles than usual).
TRENDING_QUERY = """
    WITH recent AS (
        SELECT
            unique_id,
            agency_key,
            theme_l1_code,
            published_at,
            -- Count articles in same theme in last 24h
            COUNT(*) OVER (
                PARTITION BY theme_l1_code
                ORDER BY UNIX_SECONDS(published_at)
                RANGE BETWEEN 86400 PRECEDING AND CURRENT ROW
            ) AS theme_24h_count,
            -- Average daily count for theme in last 7 days
            COUNT(*) OVER (
                PARTITION BY theme_l1_code
                ORDER BY UNIX_SECONDS(published_at)
                RANGE BETWEEN 604800 PRECEDING AND CURRENT ROW
            ) / 7.0 AS theme_7d_avg_daily
        FROM `{project_id}.dgb_gold.fato_noticias`
        WHERE published_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    )
    SELECT
        unique_id,
        theme_l1_code,
        theme_24h_count,
        theme_7d_avg_daily,
        CASE
            WHEN theme_7d_avg_daily > 0 THEN
                ROUND(theme_24h_count / theme_7d_avg_daily, 3)
            ELSE 0.0
        END AS trending_score
    FROM recent
    WHERE published_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    ORDER BY trending_score DESC
"""


def fetch_trending_scores(project_id: str) -> pd.DataFrame:
    """Query BigQuery for trending scores.

    Args:
        project_id: GCP project ID

    Returns:
        DataFrame with columns [unique_id, trending_score, ...]
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    query = TRENDING_QUERY.format(project_id=project_id)
    df = client.query(query).to_dataframe()
    logger.info(f"Fetched {len(df)} trending scores from BigQuery")
    return df


def batch_upsert_trending(db_url: str, scores_df: pd.DataFrame) -> int:
    """Batch upsert trending_score into news_features.

    Args:
        db_url: PostgreSQL connection string
        scores_df: DataFrame with columns [unique_id, trending_score]

    Returns:
        Number of rows updated
    """
    import json

    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

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
            for _, row in scores_df.iterrows():
                features = json.dumps({"trending_score": float(row["trending_score"])})
                conn.execute(upsert_sql, {"uid": row["unique_id"], "features": features})
                count += 1
        logger.info(f"Upserted {count} trending scores to news_features")
    finally:
        engine.dispose()
    return count
