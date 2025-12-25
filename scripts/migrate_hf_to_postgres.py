#!/usr/bin/env python3
"""
Migrate news data from HuggingFace Dataset to PostgreSQL.

This script loads data from the HuggingFace govbrnews dataset and migrates
it to PostgreSQL in batches, with progress tracking and error handling.

Usage:
    python scripts/migrate_hf_to_postgres.py
    python scripts/migrate_hf_to_postgres.py --batch-size 500 --max-records 1000
    python scripts/migrate_hf_to_postgres.py --dry-run  # Test without inserting
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from datasets import load_dataset
from loguru import logger
from tqdm import tqdm

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from data_platform.managers import PostgresManager
from data_platform.models import NewsInsert


def parse_datetime(dt_input: Optional[any]) -> Optional[datetime]:
    """Parse datetime string or object to datetime object."""
    if not dt_input:
        return None

    # If already a datetime object, return it (ensure it has timezone)
    if isinstance(dt_input, datetime):
        if dt_input.tzinfo is None:
            return dt_input.replace(tzinfo=timezone.utc)
        return dt_input

    # If not a string, can't parse
    if not isinstance(dt_input, str):
        return None

    try:
        # Try ISO format first
        if "T" in dt_input:
            if dt_input.endswith("Z"):
                dt_input = dt_input[:-1] + "+00:00"
            return datetime.fromisoformat(dt_input)

        # Try common formats
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(dt_input, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        logger.warning(f"Could not parse datetime: {dt_input}")
        return None

    except Exception as e:
        logger.warning(f"Error parsing datetime '{dt_input}': {e}")
        return None


def map_hf_to_postgres(
    row: Dict[str, Any],
    manager: PostgresManager,
    agency_map: Dict[str, int],
    theme_map: Dict[str, int],
) -> Optional[NewsInsert]:
    """
    Map HuggingFace row to PostgreSQL NewsInsert model.

    Args:
        row: HuggingFace dataset row
        manager: PostgresManager instance
        agency_map: agency_key -> agency_id mapping
        theme_map: theme_code -> theme_id mapping

    Returns:
        NewsInsert object or None if invalid
    """
    # Required fields
    unique_id = row.get("unique_id")
    agency_key = row.get("agency")
    title = row.get("title")
    published_at_str = row.get("published_at")

    if not all([unique_id, agency_key, title, published_at_str]):
        logger.warning(f"Missing required fields: {row}")
        return None

    # Parse published_at
    published_at = parse_datetime(published_at_str)
    if not published_at:
        logger.warning(f"Invalid published_at for {unique_id}: {published_at_str}")
        return None

    # Get agency_id
    agency_id = agency_map.get(agency_key)
    if not agency_id:
        logger.warning(f"Unknown agency: {agency_key} for {unique_id}")
        return None

    # Get theme IDs (HuggingFace uses theme_1_level_X_code field names)
    theme_l1 = row.get("theme_1_level_1_code")
    theme_l2 = row.get("theme_1_level_2_code")
    theme_l3 = row.get("theme_1_level_3_code")
    most_specific_theme = row.get("most_specific_theme_code")

    theme_l1_id = theme_map.get(theme_l1) if theme_l1 else None
    theme_l2_id = theme_map.get(theme_l2) if theme_l2 else None
    theme_l3_id = theme_map.get(theme_l3) if theme_l3 else None
    most_specific_theme_id = theme_map.get(most_specific_theme) if most_specific_theme else None

    # Get agency info for denormalized fields
    agency = manager.get_agency_by_key(agency_key)
    agency_name = agency.name if agency else None

    # Parse other datetime fields
    updated_datetime = parse_datetime(row.get("updated_datetime"))
    extracted_at = parse_datetime(row.get("extracted_at"))

    # Handle tags (might be string or list)
    tags = row.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = None

    return NewsInsert(
        unique_id=unique_id,
        agency_id=agency_id,
        theme_l1_id=theme_l1_id,
        theme_l2_id=theme_l2_id,
        theme_l3_id=theme_l3_id,
        most_specific_theme_id=most_specific_theme_id,
        title=title,
        url=row.get("url"),
        image_url=row.get("image"),  # HF field is "image", not "image_url"
        video_url=row.get("video_url"),
        category=row.get("category"),
        tags=tags,
        content=row.get("content"),
        editorial_lead=row.get("editorial_lead"),
        subtitle=row.get("subtitle"),
        summary=row.get("summary"),
        published_at=published_at,
        updated_datetime=updated_datetime,
        extracted_at=extracted_at,
        agency_key=agency_key,
        agency_name=agency_name,
    )


def migrate_hf_to_postgres(
    dataset_name: str = "nitaibezerra/govbrnews",
    batch_size: int = 1000,
    max_records: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Migrate data from HuggingFace to PostgreSQL.

    Args:
        dataset_name: HuggingFace dataset name
        batch_size: Number of records per batch
        max_records: Maximum records to migrate (None = all)
        dry_run: If True, don't actually insert data

    Returns:
        Dictionary with migration statistics
    """
    logger.info("=" * 60)
    logger.info("Migrate HuggingFace → PostgreSQL")
    logger.info("=" * 60)

    if dry_run:
        logger.warning("DRY RUN MODE - No data will be inserted")

    # Load dataset
    logger.info(f"Loading dataset: {dataset_name}")
    try:
        dataset = load_dataset(dataset_name, split="train")
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        sys.exit(1)

    total_rows = len(dataset)
    logger.info(f"Dataset loaded: {total_rows:,} records")

    if max_records:
        dataset = dataset.select(range(min(max_records, total_rows)))
        logger.info(f"Limited to {max_records:,} records")

    # Initialize PostgresManager
    logger.info("Connecting to PostgreSQL...")
    with PostgresManager() as manager:
        # Load cache
        manager.load_cache()

        # Build agency and theme mappings
        logger.info("Building mappings...")
        agency_map = {
            agency.key: agency.id for agency in manager._agencies_by_key.values()
        }
        theme_map = {theme.code: theme.id for theme in manager._themes_by_code.values()}

        logger.info(
            f"Loaded {len(agency_map)} agencies, {len(theme_map)} themes from cache"
        )

        # Migration stats
        stats = {
            "total": len(dataset),
            "processed": 0,
            "inserted": 0,
            "skipped": 0,
            "errors": 0,
        }

        # Process in batches
        batch = []
        with tqdm(total=len(dataset), desc="Migrating", unit="records") as pbar:
            for idx, row in enumerate(dataset):
                try:
                    # Map to NewsInsert
                    news = map_hf_to_postgres(row, manager, agency_map, theme_map)

                    if news:
                        batch.append(news)
                    else:
                        stats["skipped"] += 1

                    # Insert batch when full
                    if len(batch) >= batch_size:
                        if not dry_run:
                            inserted = manager.insert(batch, allow_update=False)
                            stats["inserted"] += inserted
                        else:
                            stats["inserted"] += len(batch)

                        batch = []

                    stats["processed"] += 1
                    pbar.update(1)

                except Exception as e:
                    logger.error(f"Error processing row {idx}: {e}")
                    stats["errors"] += 1
                    pbar.update(1)

            # Insert remaining batch
            if batch:
                if not dry_run:
                    inserted = manager.insert(batch, allow_update=False)
                    stats["inserted"] += inserted
                else:
                    stats["inserted"] += len(batch)

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        logger.info(f"Total records:    {stats['total']:,}")
        logger.info(f"Processed:        {stats['processed']:,}")
        logger.info(f"Inserted:         {stats['inserted']:,}")
        logger.info(f"Skipped:          {stats['skipped']:,}")
        logger.info(f"Errors:           {stats['errors']:,}")

        if not dry_run:
            # Verify count
            db_count = manager.count()
            logger.info(f"\nDatabase count:   {db_count:,}")
        else:
            logger.warning("DRY RUN - No data was actually inserted")

        logger.info("=" * 60)

        return stats


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate news from HuggingFace to PostgreSQL"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="nitaibezerra/govbrnews",
        help="HuggingFace dataset name (default: nitaibezerra/govbrnews)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for inserts (default: 1000)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Maximum records to migrate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test mode - don't insert data",
    )
    args = parser.parse_args()

    # Configure logger
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<level>{level: <8}</level> | <cyan>{message}</cyan>",
    )

    # Run migration
    stats = migrate_hf_to_postgres(
        dataset_name=args.dataset,
        batch_size=args.batch_size,
        max_records=args.max_records,
        dry_run=args.dry_run,
    )

    # Exit code
    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
