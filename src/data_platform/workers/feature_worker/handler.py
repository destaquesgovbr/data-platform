"""Feature computation handler — fetches article, computes features, upserts."""

import json
import logging
from typing import Any

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.feature_worker.features import (
    compute_all,
    compute_annotations_source_hash,
    compute_content_annotations,
)

logger = logging.getLogger(__name__)


def _coerce_entities(value: Any) -> list[dict[str, Any]]:
    """Normalize a features.entities blob into a list of mention dicts."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [e for e in value if isinstance(e, dict)]


def _fetch_article_via_graphql(unique_id: str, gql_client) -> dict | None:
    """Fetch article fields needed for feature computation via GraphQL.

    The `features` blob (already returned by NEWS_BY_ID_QUERY) is surfaced so the
    handler can derive content annotations from the current entity mentions.
    """
    from data_platform.clients.graphql_client import NEWS_BY_ID_QUERY

    data = gql_client.query(NEWS_BY_ID_QUERY, {"uniqueId": unique_id})
    article = data.get("newsById")
    if not article:
        return None
    features = article.get("features")
    entities = _coerce_entities(features.get("entities")) if isinstance(features, dict) else []
    return {
        "unique_id": article.get("uniqueId"),
        "content": article.get("content"),
        "image_url": article.get("imageUrl"),
        "video_url": article.get("videoUrl"),
        "published_at": article.get("publishedAt"),
        "entities": entities,
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

    # 3. Derive deterministic content annotations (semantic-lens offsets) from the
    #    article's CURRENT entity mentions. If entities are absent (race with the
    #    data-science enrichment worker that writes features.entities), emit an
    #    empty list — a later recompute will fill it in. Never crash.
    content = article.get("content")
    entities = _coerce_entities(article.get("entities"))
    annotations = compute_content_annotations(content, entities)
    features["content_annotations"] = annotations
    features["annotations_source_hash"] = compute_annotations_source_hash(content, entities)

    # 4. Upsert features
    if gql_client:
        _upsert_features_via_graphql(unique_id, features, gql_client)
    else:
        pg.upsert_features(unique_id, features)
    logger.info(
        f"Computed {len(features)} features for {unique_id} "
        f"({len(annotations)} content annotations)"
    )

    return {
        "status": "computed",
        "unique_id": unique_id,
        "features": list(features.keys()),
    }


def _fetch_article(unique_id: str, pg: PostgresManager) -> dict | None:
    """Fetch article fields needed for feature computation.

    Also pulls the current `news_features.features.entities` so the handler can
    derive content annotations. Entities may be absent (not yet enriched) — the
    LEFT JOIN yields NULL and the caller treats it as no annotations.
    """
    conn = pg.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT n.unique_id, n.content, n.image_url, n.video_url, n.published_at,
                   nf.features->'entities' AS entities
            FROM news n
            LEFT JOIN news_features nf ON n.unique_id = nf.unique_id
            WHERE n.unique_id = %s
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
            "entities": _coerce_entities(row[5]),
        }
    finally:
        cursor.close()
        pg.put_connection(conn)
