"""
Typesense Sync Worker — business logic.

Fetches a news article from PostgreSQL (with themes + embeddings)
and upserts it to the Typesense collection.

Supports fetching via GraphQL (preferred) or direct PostgreSQL (fallback).
"""

import pandas as pd
from loguru import logger

from data_platform.clients.graphql_client import GraphQLClient, NEWS_FOR_TYPESENSE_QUERY
from data_platform.managers.postgres_manager import PostgresManager
from data_platform.typesense.client import get_client
from data_platform.typesense.collection import COLLECTION_NAME, create_collection
from data_platform.typesense.indexer import prepare_document
from data_platform.utils.datetime_utils import calculate_published_week

# Mapping from GraphQL camelCase field names to snake_case names expected by prepare_document.
# The left side is the GraphQL response key; the right side is the dict key for prepare_document.
_GRAPHQL_TO_SNAKE: dict[str, str] = {
    "uniqueId": "unique_id",
    "title": "title",
    "url": "url",
    "imageUrl": "image",
    "videoUrl": "video_url",
    "content": "content",
    "summary": "summary",
    "subtitle": "subtitle",
    "editorialLead": "editorial_lead",
    "category": "category",
    "tags": "tags",
    "agencyKey": "agency",
    "agencyName": "agency_name",
    "publishedAt": "published_at",
    "extractedAt": "extracted_at",
    "themL1Code": "theme_1_level_1_code",
    "themL1Label": "theme_1_level_1_label",
    "themL2Code": "theme_1_level_2_code",
    "themL2Label": "theme_1_level_2_label",
    "themL3Code": "theme_1_level_3_code",
    "themL3Label": "theme_1_level_3_label",
    "mostSpecificThemeCode": "most_specific_theme_code",
    "mostSpecificThemeLabel": "most_specific_theme_label",
    "contentEmbedding": "content_embedding",
    "sentimentLabel": "sentiment_label",
    "sentimentScore": "sentiment_score",
    "trendingScore": "trending_score",
    "wordCount": "word_count",
    "hasImage": "has_image",
    "hasVideo": "has_video",
    "imageBroken": "image_broken",
    "readabilityFlesch": "readability_flesch",
}

# Feature keys (dentro do JSON `features`) que prepare_document consome diretamente.
# entities → lista de {text, type, count, canonical_id?}; view_count → int.
# O blob `features` é exposto inteiro pela query GraphQL (e por `nf.features->'entities'`
# no caminho PostgreSQL), portanto `canonical_id` — quando já canonicalizado — chega
# junto sem precisar de seleção extra. extract_entity_fields() lê esse campo.
_FEATURES_PASSTHROUGH: tuple[str, ...] = ("entities", "view_count")


def _parse_iso_to_epoch(iso_str: str | None) -> int:
    """Convert an ISO-8601 datetime string to a Unix epoch integer."""
    if not iso_str:
        return 0
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return 0


def _map_graphql_row(gql_row: dict) -> dict:
    """
    Map a GraphQL camelCase response dict to the snake_case dict format
    expected by prepare_document().
    """
    mapped: dict = {}
    for gql_key, snake_key in _GRAPHQL_TO_SNAKE.items():
        if gql_key in gql_row and gql_row[gql_key] is not None:
            mapped[snake_key] = gql_row[gql_key]

    # Extrai entidades e view_count do JSON `features` (não expostos como campos
    # escalares pelo schema graphql; chegam dentro do blob `features`).
    features = gql_row.get("features")
    if isinstance(features, dict):
        for key in _FEATURES_PASSTHROUGH:
            value = features.get(key)
            if value is not None:
                mapped[key] = value

    # Convert ISO datetime strings to epoch timestamps (prepare_document expects these)
    if "published_at" in mapped:
        ts = _parse_iso_to_epoch(mapped.pop("published_at"))
        mapped["published_at_ts"] = ts
        if ts > 0:
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            mapped["published_year"] = dt.year
            mapped["published_month"] = dt.month

    if "extracted_at" in mapped:
        mapped["extracted_at_ts"] = _parse_iso_to_epoch(mapped.pop("extracted_at"))

    return mapped


def fetch_news_for_typesense_via_graphql(
    gql_client: GraphQLClient, unique_id: str
) -> dict | None:
    """
    Fetch a single news article via GraphQL for Typesense indexing.

    Args:
        gql_client: Initialized GraphQLClient instance.
        unique_id: Article unique_id.

    Returns:
        Dict with snake_case keys ready for prepare_document(), or None if not found.
    """
    data = gql_client.query(NEWS_FOR_TYPESENSE_QUERY, {"uniqueId": unique_id})
    gql_row = data.get("newsForTypesense")
    if gql_row is None:
        return None
    return _map_graphql_row(gql_row)


def fetch_news_for_typesense(pg: PostgresManager, unique_id: str) -> dict | None:
    """
    Fetch a single news article with all Typesense fields (themes, embedding).

    Uses the same query as _build_typesense_query() but filtered by unique_id.

    Returns:
        Dict with Typesense-ready column names, or None if not found.
    """
    conn = pg.get_connection()
    try:
        query = pg._build_typesense_query() + " WHERE n.unique_id = %s"
        df = pd.read_sql_query(query, pg.engine, params=(unique_id,))
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    finally:
        pg.put_connection(conn)


def upsert_to_typesense(
    unique_id: str,
    pg: PostgresManager | None = None,
    gql_client: GraphQLClient | None = None,
) -> bool:
    """
    Fetch article and upsert to Typesense.

    Uses GraphQL when gql_client is provided, otherwise falls back to
    direct PostgreSQL access.

    Args:
        unique_id: Article unique_id to sync.
        pg: Optional pre-initialized PostgresManager (fallback).
        gql_client: Optional GraphQLClient for GraphQL-based fetching.

    Returns:
        True if upserted successfully, False otherwise.
    """
    close_pg = False

    try:
        # Prefer GraphQL when a client is provided
        if gql_client is not None:
            row_dict = fetch_news_for_typesense_via_graphql(gql_client, unique_id)
            source = "GraphQL"
        else:
            if pg is None:
                pg = PostgresManager(max_connections=2)
                close_pg = True
            row_dict = fetch_news_for_typesense(pg, unique_id)
            source = "PostgreSQL"
        if row_dict is None:
            logger.warning(f"Article not found via {source}: {unique_id}")
            return False

        # Calculate published_week
        ts = row_dict.get("published_at_ts")
        if ts and ts > 0:
            row_dict["published_week"] = calculate_published_week(ts)

        # Convert to pandas Series for prepare_document compatibility
        row = pd.Series(row_dict)
        doc = prepare_document(row)

        # Upsert to Typesense
        client = get_client()
        create_collection(client)
        client.collections[COLLECTION_NAME].documents.upsert(doc)

        logger.info(f"Upserted to Typesense: {unique_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to upsert {unique_id}: {e}")
        return False

    finally:
        if close_pg:
            pg.close_all()
