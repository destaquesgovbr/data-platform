"""Bronze Writer handler — fetches article from PG/GraphQL, writes raw JSON to GCS."""

import logging
import os

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.utils.datetime_utils import parse_iso_datetime
from data_platform.workers.bronze_writer.storage import build_gcs_path, write_to_gcs

logger = logging.getLogger(__name__)


# Campo do GraphQL (NewsRecordType) → chave do JSON bronze (mesmos nomes do caminho PG).
# Toda chave precisa estar selecionada em NEWS_BY_ID_QUERY (teste de contrato).
_GRAPHQL_TO_SNAKE: dict[str, str] = {
    "uniqueId": "unique_id",
    "title": "title",
    "url": "url",
    "imageUrl": "image_url",
    "videoUrl": "video_url",
    "content": "content",
    "summary": "summary",
    "subtitle": "subtitle",
    "editorialLead": "editorial_lead",
    "category": "category",
    "tags": "tags",
    "agencyKey": "agency_key",
    "agencyName": "agency_name",
    "publishedAt": "published_at",
    "extractedAt": "extracted_at",
    "themeL1Code": "theme_l1_code",
    "themeL1Label": "theme_l1_label",
    "themeL2Code": "theme_l2_code",
    "themeL2Label": "theme_l2_label",
    "themeL3Code": "theme_l3_code",
    "themeL3Label": "theme_l3_label",
    "mostSpecificThemeCode": "most_specific_theme_code",
    "mostSpecificThemeLabel": "most_specific_theme_label",
    "features": "features",
}

# DateTime do GraphQL chega como str ISO; o caminho PG entrega datetime.
_DATETIME_FIELDS = ("published_at", "extracted_at")


def _fetch_full_article_via_graphql(unique_id: str, gql_client) -> dict | None:
    """Fetch full article via GraphQL, mapping camelCase to snake_case for compatibility.

    `published_at`/`extracted_at` viram datetime UTC: `build_gcs_path` particiona
    por `published_at.strftime(...)` e o JSON sai no mesmo formato do caminho PG.
    """
    from data_platform.clients.graphql_client import NEWS_BY_ID_QUERY

    data = gql_client.query(NEWS_BY_ID_QUERY, {"uniqueId": unique_id})
    article = data.get("newsById")
    if not article:
        return None
    mapped = {snake: article.get(camel) for camel, snake in _GRAPHQL_TO_SNAKE.items()}
    for key in _DATETIME_FIELDS:
        mapped[key] = parse_iso_datetime(mapped[key])
    return mapped


def handle_bronze_write(unique_id: str, pg: PostgresManager, gql_client=None) -> dict:
    """
    Fetch full article and write raw JSON to GCS Bronze layer.

    Uses GraphQL if gql_client is provided, otherwise falls back to PostgresManager.

    Path: gs://{bucket}/bronze/news/YYYY/MM/DD/{unique_id}.json

    Args:
        unique_id: Article unique_id
        pg: PostgresManager instance
        gql_client: Optional GraphQLClient instance

    Returns:
        dict with status and gcs_path
    """
    bucket_name = os.environ.get("GCS_BUCKET", "")
    if not bucket_name:
        logger.error("GCS_BUCKET not set")
        return {"status": "error", "unique_id": unique_id, "reason": "GCS_BUCKET not set"}

    # 1. Fetch full article
    if gql_client:
        article = _fetch_full_article_via_graphql(unique_id, gql_client)
    else:
        article = _fetch_full_article(unique_id, pg)
    if not article:
        logger.warning(f"Article {unique_id} not found")
        return {"status": "not_found", "unique_id": unique_id}

    # 2. Build GCS path
    gcs_path = build_gcs_path(unique_id, article["published_at"])

    # 3. Write to GCS
    write_to_gcs(bucket_name, gcs_path, article)

    logger.info(f"Bronze write complete: {unique_id} → gs://{bucket_name}/{gcs_path}")
    return {"status": "written", "unique_id": unique_id, "gcs_path": gcs_path}


def _fetch_full_article(unique_id: str, pg: PostgresManager) -> dict | None:
    """Fetch all article fields for Bronze archival."""
    conn = pg.get_connection()
    try:
        from psycopg2.extras import RealDictCursor

        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT
                n.*,
                a.key as agency_key_joined,
                a.name as agency_name_joined,
                t1.code as theme_l1_code, t1.label as theme_l1_label,
                t2.code as theme_l2_code, t2.label as theme_l2_label,
                t3.code as theme_l3_code, t3.label as theme_l3_label,
                tm.code as most_specific_theme_code, tm.label as most_specific_theme_label
            FROM news n
            LEFT JOIN agencies a ON n.agency_id = a.id
            LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
            LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
            LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
            LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
            WHERE n.unique_id = %s
            """,
            (unique_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        # Convert to plain dict (RealDictRow -> dict)
        return dict(row)
    finally:
        cursor.close()
        pg.put_connection(conn)
