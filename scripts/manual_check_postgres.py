#!/usr/bin/env python3
"""
Simple test script for PostgresManager.

Tests basic functionality: connection, cache loading, and queries.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_platform.managers import PostgresManager
from loguru import logger


def main():
    """Test PostgresManager."""
    logger.info("=" * 60)
    logger.info("Testing PostgresManager")
    logger.info("=" * 60)

    # Test 1: Connection and initialization
    logger.info("\n1. Creating PostgresManager...")
    with PostgresManager() as manager:
        # Test 2: Load cache
        logger.info("\n2. Loading cache...")
        manager.load_cache()

        # Test 3: Get agency by key
        logger.info("\n3. Testing get_agency_by_key...")
        agency = manager.get_agency_by_key("mec")
        if agency:
            logger.success(f"Found agency: {agency.name} (id={agency.id})")
        else:
            logger.warning("MEC agency not found")

        # Test 4: Get theme by code
        logger.info("\n4. Testing get_theme_by_code...")
        theme = manager.get_theme_by_code("01")
        if theme:
            logger.success(
                f"Found theme: {theme.full_name} (id={theme.id}, level={theme.level})"
            )
        else:
            logger.warning("Theme 01 not found")

        # Test 5: Count news
        logger.info("\n5. Testing count...")
        total = manager.count()
        logger.info(f"Total news in database: {total}")

        # Test 6: Get records for HF sync
        logger.info("\n6. Testing get_records_for_hf_sync...")
        records = manager.get_records_for_hf_sync(limit=5)
        logger.info(f"Found {len(records)} records needing HF sync")

        logger.info("\n" + "=" * 60)
        logger.success("All tests passed!")


if __name__ == "__main__":
    main()
