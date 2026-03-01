"""Compute similar article clusters using pgvector cosine similarity."""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Find top-K similar articles for each article published in the last 24h
# Uses pgvector <=> operator (cosine distance)
# Cosine similarity = 1 - cosine_distance
SIMILARITY_QUERY = """
    WITH target_articles AS (
        SELECT unique_id, content_embedding
        FROM news
        WHERE published_at >= NOW() - INTERVAL '%s days'
          AND content_embedding IS NOT NULL
    )
    SELECT
        t.unique_id,
        n.unique_id AS similar_id,
        1 - (t.content_embedding <=> n.content_embedding) AS similarity
    FROM target_articles t
    CROSS JOIN LATERAL (
        SELECT unique_id, content_embedding
        FROM news
        WHERE unique_id != t.unique_id
          AND content_embedding IS NOT NULL
          AND 1 - (content_embedding <=> t.content_embedding) > %s
        ORDER BY content_embedding <=> t.content_embedding
        LIMIT %s
    ) n
    ORDER BY t.unique_id, similarity DESC
"""

DEFAULT_SIMILARITY_THRESHOLD = 0.8
DEFAULT_TOP_K = 5
DEFAULT_LOOKBACK_DAYS = 1


def fetch_similar_articles(
    db_url: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> pd.DataFrame:
    """Find similar articles using pgvector cosine similarity.

    Args:
        db_url: PostgreSQL connection string
        lookback_days: How many days back to look for target articles
        threshold: Minimum cosine similarity (0-1)
        top_k: Max similar articles per target

    Returns:
        DataFrame with columns [unique_id, similar_id, similarity]
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        df = pd.read_sql_query(
            SIMILARITY_QUERY,
            engine,
            params=(lookback_days, threshold, top_k),
        )
        logger.info(f"Found {len(df)} similarity pairs for {df['unique_id'].nunique()} articles")
        return df
    finally:
        engine.dispose()


def group_similar_articles(similarities_df: pd.DataFrame) -> dict[str, list[str]]:
    """Group similarity pairs into {unique_id: [similar_id1, similar_id2, ...]}.

    Args:
        similarities_df: DataFrame with columns [unique_id, similar_id, similarity]

    Returns:
        Dict mapping unique_id to list of similar article IDs (ordered by similarity desc)
    """
    if similarities_df.empty:
        return {}

    groups = {}
    for unique_id, group in similarities_df.groupby("unique_id"):
        groups[unique_id] = group.sort_values("similarity", ascending=False)["similar_id"].tolist()

    return groups


def batch_upsert_clusters(db_url: str, clusters: dict[str, list[str]]) -> int:
    """Batch upsert similar_articles into news_features.

    Args:
        db_url: PostgreSQL connection string
        clusters: Dict mapping unique_id to list of similar article IDs

    Returns:
        Number of articles updated
    """
    from data_platform.managers.postgres_manager import PostgresManager

    pg = PostgresManager(db_url=db_url, max_connections=2)
    count = 0
    try:
        for unique_id, similar_ids in clusters.items():
            if pg.upsert_features(unique_id, {"similar_articles": similar_ids}):
                count += 1
        logger.info(f"Upserted similar_articles for {count} articles")
    finally:
        pg.close_all()
    return count
