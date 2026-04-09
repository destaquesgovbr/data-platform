"""Batch processing for video thumbnail generation.

Used by the Airflow DAG to backfill thumbnails for existing articles.
"""

import logging
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

QUERY = """
    SELECT n.unique_id, n.video_url
    FROM news n
    LEFT JOIN news_features nf ON n.unique_id = nf.unique_id
    WHERE n.video_url IS NOT NULL
      AND n.video_url != ''
      AND (n.image_url IS NULL OR n.image_url = '')
      AND (
          nf.unique_id IS NULL
          OR (nf.features->>'thumbnail_failed')::boolean IS NOT TRUE
      )
    ORDER BY n.published_at DESC, n.unique_id ASC
    LIMIT :batch_size
"""


def fetch_articles_needing_thumbnails(
    engine: Engine,
    batch_size: int = 100,
) -> list[dict[str, Any]]:
    """Query for articles with video_url but no image_url.

    Excludes articles previously marked with thumbnail_failed.

    Args:
        engine: SQLAlchemy engine.
        batch_size: Maximum number of articles to fetch.

    Returns:
        List of dicts: [{unique_id, video_url}, ...]
    """
    df = pd.read_sql_query(text(QUERY), engine, params={"batch_size": batch_size})

    if df.empty:
        logger.info("No articles needing thumbnails")
        return []

    articles = df.to_dict(orient="records")
    logger.info(f"Found {len(articles)} articles needing thumbnails")
    return articles
