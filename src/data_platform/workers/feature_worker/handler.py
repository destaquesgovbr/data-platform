"""Feature computation handler — fetches article, computes features, upserts."""

import json
import logging

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.feature_worker.features import compute_all

logger = logging.getLogger(__name__)


def _fetch_article_via_graphql(unique_id: str, gql_client) -> dict | None:
    """Fetch article fields needed for feature computation via GraphQL."""
    from data_platform.clients.graphql_client import NEWS_BY_ID_QUERY

    data = gql_client.query(NEWS_BY_ID_QUERY, {"uniqueId": unique_id})
    article = data.get("newsById")
    if not article:
        return None
    return {
        "unique_id": article.get("uniqueId"),
        "content": article.get("content"),
        "image_url": article.get("imageUrl"),
        "video_url": article.get("videoUrl"),
        "published_at": article.get("publishedAt"),
    }


def _upsert_features_via_graphql(unique_id: str, features: dict, gql_client) -> None:
    """Upsert computed features via GraphQL mutation."""
    from data_platform.clients.graphql_client import UPSERT_FEATURES_MUTATION

    gql_client.mutate(
        UPSERT_FEATURES_MUTATION,
        {"uniqueId": unique_id, "features": json.dumps(features)},
    )


def handle_feature_computation(unique_id: str, pg: PostgresManager, gql_client=None) -> dict:
    """
    Fetch article, compute local features, upsert to news_features.

    Uses GraphQL if gql_client is provided, otherwise falls back to PostgresManager.

    Args:
        unique_id: Article unique_id
        pg: PostgresManager instance
        gql_client: Optional GraphQLClient instance

    Returns:
        dict with status and computed feature keys
    """
    # 1. Fetch article
    if gql_client:
        article = _fetch_article_via_graphql(unique_id, gql_client)
    else:
        article = _fetch_article(unique_id, pg)
    if not article:
        logger.warning(f"Article {unique_id} not found")
        return {"status": "not_found", "unique_id": unique_id}

    # 2. Compute all local features
    features = compute_all(article)

    # 3. Upsert features
    if gql_client:
        _upsert_features_via_graphql(unique_id, features, gql_client)
    else:
        pg.upsert_features(unique_id, features)
    logger.info(f"Computed {len(features)} features for {unique_id}")

    return {
        "status": "computed",
        "unique_id": unique_id,
        "features": list(features.keys()),
    }


def _fetch_article(unique_id: str, pg: PostgresManager) -> dict | None:
    """Fetch article fields needed for feature computation."""
    conn = pg.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT unique_id, content, image_url, video_url, published_at
            FROM news
            WHERE unique_id = %s
            """,
            (unique_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "unique_id": row[0],
            "content": row[1],
            "image_url": row[2],
            "video_url": row[3],
            "published_at": row[4],
        }
    finally:
        cursor.close()
        pg.put_connection(conn)
