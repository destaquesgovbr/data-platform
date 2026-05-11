"""Detect and remove Typesense documents with no matching record in PostgreSQL."""

import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


def get_typesense_doc_ids(client, collection_name: str) -> set[str]:
    """Export all document IDs from a Typesense collection."""
    raw = client.collections[collection_name].documents.export({"include_fields": "id"})
    if not raw.strip():
        return set()
    ids = set()
    for line in raw.strip().split("\n"):
        doc = json.loads(line)
        ids.add(doc["id"])
    return ids


def get_pg_unique_ids(db_url: str) -> set[str]:
    """Fetch all unique_ids from the news table."""
    engine = create_engine(db_url, poolclass=NullPool)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT unique_id FROM news"))
        ids = {row[0] for row in result.fetchall()}
    engine.dispose()
    return ids


def find_orphans(typesense_ids: set[str], pg_ids: set[str]) -> set[str]:
    """Return IDs present in Typesense but not in PostgreSQL."""
    return typesense_ids - pg_ids


def delete_orphans(
    client,
    collection_name: str,
    orphan_ids: set[str],
    dry_run: bool = False,
) -> dict:
    """Delete orphan documents from Typesense.

    Returns a summary dict with counts of deleted, not_found, and errors.
    """
    if dry_run:
        return {"would_delete": len(orphan_ids)}

    from typesense.exceptions import ObjectNotFound

    deleted = 0
    not_found = 0
    errors = 0

    for doc_id in orphan_ids:
        try:
            client.collections[collection_name].documents[doc_id].delete()
            deleted += 1
        except ObjectNotFound:
            not_found += 1
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to delete {doc_id}: {e}")

    return {"deleted": deleted, "not_found": not_found, "errors": errors}


def detect_typesense_orphans(
    collection_name: str = "news",
    dry_run: bool = True,
) -> dict:
    """High-level orchestrator: detect and optionally remove orphans."""
    import os

    from data_platform.typesense.client import get_client

    db_url = os.environ["DATABASE_URL"]
    client = get_client()

    logger.info(f"Exporting document IDs from Typesense collection '{collection_name}'...")
    ts_ids = get_typesense_doc_ids(client, collection_name)
    logger.info(f"Typesense documents: {len(ts_ids)}")

    logger.info("Fetching unique_ids from PostgreSQL...")
    pg_ids = get_pg_unique_ids(db_url)
    logger.info(f"PostgreSQL records: {len(pg_ids)}")

    orphans = find_orphans(ts_ids, pg_ids)
    logger.info(f"Orphans detected: {len(orphans)}")

    if not orphans:
        return {"typesense_docs": len(ts_ids), "pg_records": len(pg_ids), "orphans": 0}

    result = delete_orphans(client, collection_name, orphans, dry_run=dry_run)
    result["typesense_docs"] = len(ts_ids)
    result["pg_records"] = len(pg_ids)
    result["orphans"] = len(orphans)
    return result
