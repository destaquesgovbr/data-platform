"""Compute similar article clusters using pgvector cosine similarity."""

import logging
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GraphQL-based alternatives
# ---------------------------------------------------------------------------


def fetch_similar_articles_via_graphql(
    gql_client: Any,
    unique_ids: list[str],
    threshold: float = 0.8,
    limit: int = 5,
) -> pd.DataFrame:
    """Fetch similar articles via GraphQL instead of direct pgvector query.

    Args:
        gql_client: GraphQLClient instance
        unique_ids: List of article unique_ids to find similarities for
        threshold: Minimum cosine similarity (0-1)
        limit: Max similar articles per target

    Returns:
        DataFrame with columns [unique_id, similar_id, similarity]
    """
    from data_platform.clients.graphql_client import SIMILAR_ARTICLES_QUERY

    rows: list[dict] = []
    for uid in unique_ids:
        data = gql_client.query(
            SIMILAR_ARTICLES_QUERY,
            {"uniqueId": uid, "threshold": threshold, "limit": limit},
        )
        for item in data.get("similarArticles", []):
            rows.append({
                "unique_id": uid,
                "similar_id": item["uniqueId"],
                "similarity": item["similarity"],
            })

    df = pd.DataFrame(rows, columns=["unique_id", "similar_id", "similarity"])
    logger.info(
        f"[GraphQL] Found {len(df)} similarity pairs for {df['unique_id'].nunique() if not df.empty else 0} articles"
    )
    return df


def batch_upsert_clusters_via_graphql(
    gql_client: Any,
    clusters: dict[str, list[str]],
) -> int:
    """Batch upsert similar_articles into news_features via GraphQL.

    Args:
        gql_client: GraphQLClient instance
        clusters: Dict mapping unique_id to list of similar article IDs

    Returns:
        Number of articles processed
    """
    from data_platform.clients.graphql_client import BATCH_UPSERT_FEATURES_MUTATION

    items = [
        {"uniqueId": uid, "features": {"similar_articles": similar_ids}}
        for uid, similar_ids in clusters.items()
    ]

    if not items:
        return 0

    data = gql_client.mutate(
        BATCH_UPSERT_FEATURES_MUTATION,
        {"items": items},
    )
    result = data.get("batchUpsertFeatures", {})
    processed = result.get("processed", 0)
    failed = result.get("failed", 0)

    logger.info(f"[GraphQL] Upserted similar_articles: {processed} processed, {failed} failed")
    return processed

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
            for unique_id, similar_ids in clusters.items():
                features = json.dumps({"similar_articles": similar_ids})
                conn.execute(upsert_sql, {"uid": unique_id, "features": features})
                count += 1
        logger.info(f"Upserted similar_articles for {count} articles")
    finally:
        engine.dispose()
    return count
