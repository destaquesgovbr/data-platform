"""
Cleanup URL-based duplicates from news table.

For each group of rows sharing (agency_key, url), keep the canonical record:
  1. Prefer records WITH embedding (embedding_generated_at IS NOT NULL)
  2. Tiebreaker: lowest id (oldest in pipeline)

Deletes non-canonical records + their news_features. Removes orphaned
Typesense documents if TYPESENSE_API_KEY is set.

Usage:
  python 011_cleanup_url_duplicates.py --dry-run       # preview only
  python 011_cleanup_url_duplicates.py --confirm        # execute
  python 011_cleanup_url_duplicates.py --confirm --batch-size 500

Ref: destaquesgovbr/portal#108, destaquesgovbr/data-platform#138
"""

import argparse
import logging
import os
import sys
import time


BATCH_SIZE = 1000

FIND_DUPLICATES_SQL = """
    SELECT agency_key, url,
        array_agg(id ORDER BY
            CASE WHEN embedding_generated_at IS NOT NULL THEN 0 ELSE 1 END,
            id
        ) as ids,
        array_agg(unique_id ORDER BY
            CASE WHEN embedding_generated_at IS NOT NULL THEN 0 ELSE 1 END,
            id
        ) as unique_ids
    FROM news
    WHERE url IS NOT NULL
    GROUP BY agency_key, url
    HAVING count(*) > 1
"""


def describe() -> str:
    return "Cleanup de duplicatas por (agency_key, url) na tabela news"


def _find_duplicate_groups(conn):
    cursor = conn.cursor()
    cursor.execute(FIND_DUPLICATES_SQL)
    groups = cursor.fetchall()
    cursor.close()
    return groups


def _delete_batch(conn, unique_ids_to_delete):
    cursor = conn.cursor()

    # news_features rows are cascade-deleted via FK ON DELETE CASCADE
    cursor.execute(
        "DELETE FROM news WHERE unique_id = ANY(%s)",
        (unique_ids_to_delete,),
    )
    news_deleted = cursor.rowcount

    cursor.close()
    return news_deleted


def _try_delete_from_typesense(unique_ids):
    api_key = os.getenv("TYPESENSE_API_KEY")
    host = os.getenv("TYPESENSE_HOST")
    if not api_key or not host:
        return 0

    port = os.getenv("TYPESENSE_PORT", "8108")
    deleted = 0
    try:
        import httpx

        for uid in unique_ids:
            resp = httpx.delete(
                f"http://{host}:{port}/collections/news/documents/{uid}",
                headers={"X-TYPESENSE-API-KEY": api_key},
                timeout=5,
            )
            if resp.status_code in (200, 404):
                deleted += 1
    except Exception as e:
        logging.warning(f"Typesense cleanup error: {e}")
    if deleted < len(unique_ids):
        logging.warning(
            f"Typesense cleanup partial: {deleted}/{len(unique_ids)} documents deleted"
        )
    return deleted


def migrate(conn, dry_run: bool = False, batch_size: int = BATCH_SIZE) -> dict:
    groups = _find_duplicate_groups(conn)

    if not groups:
        return {"groups": 0, "deleted": 0, "message": "No duplicates found"}

    all_to_delete = []
    preserved_with_embedding = 0

    for agency_key, url, ids, unique_ids in groups:
        canonical_uid = unique_ids[0]
        to_delete_uids = unique_ids[1:]
        all_to_delete.extend(to_delete_uids)

        canonical_id = ids[0]
        if len(ids) > 1 and canonical_id != min(ids):
            preserved_with_embedding += 1

    if dry_run:
        return {
            "groups": len(groups),
            "to_delete": len(all_to_delete),
            "preserved_with_embedding": preserved_with_embedding,
            "preview": True,
        }

    t0 = time.time()
    total_news_deleted = 0

    for i in range(0, len(all_to_delete), batch_size):
        batch = all_to_delete[i : i + batch_size]
        news_del = _delete_batch(conn, batch)
        total_news_deleted += news_del

    # Commit PG (authoritative) before best-effort Typesense cleanup
    conn.commit()

    typesense_deleted = _try_delete_from_typesense(all_to_delete)

    elapsed = time.time() - t0

    return {
        "groups": len(groups),
        "news_deleted": total_news_deleted,
        "typesense_deleted": typesense_deleted,
        "preserved_with_embedding": preserved_with_embedding,
        "elapsed_seconds": round(elapsed, 2),
    }


def rollback(conn, dry_run: bool = False) -> dict:
    return {
        "message": "Cleanup is irreversible. Restore from backup: "
        "pg_restore -d $DATABASE_URL --clean backup_pre_cleanup_*.dump"
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=describe())
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--confirm", action="store_true", help="Execute deletions")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("Must specify --dry-run or --confirm")
        sys.exit(1)

    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        result = migrate(conn, dry_run=args.dry_run, batch_size=args.batch_size)
        print(result)
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        conn.close()
