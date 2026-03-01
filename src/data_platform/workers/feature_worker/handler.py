"""Feature computation handler — fetches article, computes features, upserts."""

import logging

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.feature_worker.features import compute_all

logger = logging.getLogger(__name__)


def handle_feature_computation(unique_id: str, pg: PostgresManager) -> dict:
    """
    Fetch article from PostgreSQL, compute local features, upsert to news_features.

    Args:
        unique_id: Article unique_id
        pg: PostgresManager instance

    Returns:
        dict with status and computed feature keys
    """
    # 1. Fetch article
    article = _fetch_article(unique_id, pg)
    if not article:
        logger.warning(f"Article {unique_id} not found")
        return {"status": "not_found", "unique_id": unique_id}

    # 2. Compute all local features
    features = compute_all(article)

    # 3. Upsert to news_features
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
