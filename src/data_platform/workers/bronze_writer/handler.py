"""Bronze Writer handler — fetches article from PG, writes raw JSON to GCS."""

import logging
import os

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.bronze_writer.storage import build_gcs_path, write_to_gcs

logger = logging.getLogger(__name__)


def handle_bronze_write(unique_id: str, pg: PostgresManager) -> dict:
    """
    Fetch full article from PostgreSQL and write raw JSON to GCS Bronze layer.

    Path: gs://{bucket}/bronze/news/YYYY/MM/DD/{unique_id}.json

    Args:
        unique_id: Article unique_id
        pg: PostgresManager instance

    Returns:
        dict with status and gcs_path
    """
    bucket_name = os.environ.get("GCS_BUCKET", "")
    if not bucket_name:
        logger.error("GCS_BUCKET not set")
        return {"status": "error", "unique_id": unique_id, "reason": "GCS_BUCKET not set"}

    # 1. Fetch full article
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
