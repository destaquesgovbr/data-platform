"""
Typesense Sync Worker — business logic.

Fetches a news article from PostgreSQL (with themes + embeddings)
and upserts it to the Typesense collection.
"""

import pandas as pd
from loguru import logger

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.typesense.client import get_client
from data_platform.typesense.collection import COLLECTION_NAME, create_collection
from data_platform.typesense.indexer import prepare_document
from data_platform.utils.datetime_utils import calculate_published_week


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


def upsert_to_typesense(unique_id: str, pg: PostgresManager | None = None) -> bool:
    """
    Fetch article from PG and upsert to Typesense.

    Args:
        unique_id: Article unique_id to sync.
        pg: Optional pre-initialized PostgresManager.

    Returns:
        True if upserted successfully, False otherwise.
    """
    close_pg = False
    if pg is None:
        pg = PostgresManager(max_connections=2)
        close_pg = True

    try:
        row_dict = fetch_news_for_typesense(pg, unique_id)
        if row_dict is None:
            logger.warning(f"Article not found in PG: {unique_id}")
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
