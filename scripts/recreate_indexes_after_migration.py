#!/usr/bin/env python3
"""
Recreate indexes after bulk migration.

This script recreates indexes that were dropped during bulk migration
for performance optimization. Run this after migration is complete.

Usage:
    python scripts/recreate_indexes_after_migration.py
    python scripts/recreate_indexes_after_migration.py --dry-run
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from loguru import logger
from data_platform.managers import PostgresManager


def recreate_indexes(dry_run: bool = False) -> None:
    """
    Recreate indexes dropped during migration.

    Indexes to recreate:
    1. idx_news_agency_date - Composite index for agency queries
    2. idx_news_synced_to_hf - Partial index for HF sync
    3. idx_news_theme_l1 - Simple index on theme_l1_id

    Note: FTS index not created - searches are done in Typesense

    Args:
        dry_run: If True, only show what would be done
    """
    logger.info("=" * 60)
    logger.info("Recreate Indexes After Migration")
    logger.info("=" * 60)

    if dry_run:
        logger.warning("DRY RUN MODE - No changes will be made")

    with PostgresManager() as manager:
        conn = manager.get_connection()
        # CONCURRENTLY requires autocommit mode
        conn.autocommit = True
        cursor = conn.cursor()

        try:
            # NOTE: FTS index not needed - searches are done in Typesense
            # If FTS is ever needed, use:
            # CREATE INDEX idx_news_fts ON news
            # USING GIN (to_tsvector('portuguese', title || ' ' || COALESCE(LEFT(content, 100000), '')))

            # 1. Composite index for agency + date queries
            logger.info("Creating idx_news_agency_date...")
            if not dry_run:
                cursor.execute("""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_agency_date
                    ON news(agency_id, published_at DESC)
                """)
            logger.success("✓ idx_news_agency_date created")

            # 3. Partial index for HF sync tracking
            logger.info("Creating idx_news_synced_to_hf...")
            if not dry_run:
                cursor.execute("""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_synced_to_hf
                    ON news(synced_to_hf_at)
                    WHERE synced_to_hf_at IS NULL
                """)
            logger.success("✓ idx_news_synced_to_hf created (partial)")

            # 4. Simple index on theme_l1_id
            logger.info("Creating idx_news_theme_l1...")
            if not dry_run:
                cursor.execute("""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_theme_l1
                    ON news(theme_l1_id)
                """)
            logger.success("✓ idx_news_theme_l1 created")

            # 5. Re-enable denormalize trigger (if needed)
            logger.info("Re-enabling denormalize_news_agency trigger...")
            if not dry_run:
                cursor.execute("""
                    ALTER TABLE news ENABLE TRIGGER denormalize_news_agency
                """)
            logger.success("✓ denormalize_news_agency trigger enabled")

            logger.info("")
            logger.info("=" * 60)
            logger.success("✓ All indexes recreated successfully!")
            logger.info("=" * 60)

            # Show index sizes
            if not dry_run:
                logger.info("")
                logger.info("Index sizes:")
                cursor.execute("""
                    SELECT
                        indexname,
                        pg_size_pretty(pg_relation_size(indexname::regclass)) as size
                    FROM pg_indexes
                    WHERE tablename = 'news'
                    ORDER BY pg_relation_size(indexname::regclass) DESC
                """)

                for row in cursor.fetchall():
                    logger.info(f"  {row[0]}: {row[1]}")

        except Exception as e:
            logger.error(f"Error recreating indexes: {e}")
            raise

        finally:
            cursor.close()
            manager.put_connection(conn)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Recreate indexes after bulk migration"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    # Configure logger
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<level>{level: <8}</level> | <level>{message}</level>",
    )

    recreate_indexes(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
