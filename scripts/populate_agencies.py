#!/usr/bin/env python3
"""
Populate agencies table from agencies.yaml

This script reads the canonical agencies.yaml file and populates the PostgreSQL
agencies table with all government agencies data.

Usage:
    python scripts/populate_agencies.py
    python scripts/populate_agencies.py --source /path/to/agencies.yaml
    python scripts/populate_agencies.py --dry-run  # Test without inserting
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any

import psycopg2
import yaml
from loguru import logger


def get_db_connection_string() -> str:
    """Get database connection string from environment or Secret Manager."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                "--secret=govbrnews-postgres-connection-string",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to fetch connection string from Secret Manager: {e}")
        logger.info("Falling back to localhost (assuming Cloud SQL Proxy)")
        return "postgresql://govbrnews_app:password@127.0.0.1:5432/govbrnews"


def load_agencies_yaml(filepath: Path) -> Dict[str, Any]:
    """Load and parse agencies.yaml file."""
    logger.info(f"Loading agencies from {filepath}")

    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if "sources" not in data:
        logger.error("Invalid agencies.yaml format: missing 'sources' key")
        sys.exit(1)

    return data["sources"]


def populate_agencies(
    agencies: Dict[str, Any], connection_string: str, dry_run: bool = False
) -> None:
    """Populate agencies table with data from YAML."""
    if dry_run:
        logger.info("DRY RUN MODE - No data will be inserted")

    logger.info(f"Found {len(agencies)} agencies to insert")

    if dry_run:
        # Just display what would be inserted
        for key, data in list(agencies.items())[:5]:
            logger.info(f"Would insert: {key} -> {data['name']}")
        logger.info(f"... and {len(agencies) - 5} more")
        return

    # Connect to database
    logger.info("Connecting to PostgreSQL...")
    try:
        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()
    except psycopg2.OperationalError as e:
        logger.error(f"Failed to connect to database: {e}")
        logger.info(
            "Make sure Cloud SQL Proxy is running: "
            "cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres"
        )
        sys.exit(1)

    try:
        # Clear existing data (for idempotency)
        logger.info("Clearing existing agencies data...")
        cursor.execute("DELETE FROM agencies")
        logger.info(f"Deleted {cursor.rowcount} existing records")

        # Insert agencies
        insert_query = """
            INSERT INTO agencies (key, name, type, parent_key, url)
            VALUES (%s, %s, %s, %s, %s)
        """

        inserted = 0
        for key, data in agencies.items():
            cursor.execute(
                insert_query,
                (
                    key,
                    data["name"],
                    data.get("type"),
                    data.get("parent"),
                    data.get("url"),
                ),
            )
            inserted += 1

        # Commit transaction
        conn.commit()
        logger.success(f"✓ Successfully inserted {inserted} agencies")

        # Verify
        cursor.execute("SELECT COUNT(*) FROM agencies")
        count = cursor.fetchone()[0]
        logger.info(f"Total agencies in database: {count}")

    except Exception as e:
        conn.rollback()
        logger.error(f"Error during insertion: {e}")
        raise

    finally:
        cursor.close()
        conn.close()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Populate agencies table from agencies.yaml"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("../agencies/agencies.yaml"),
        help="Path to agencies.yaml file (default: ../agencies/agencies.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test mode - don't insert data",
    )
    args = parser.parse_args()

    # Configure logger
    logger.remove()
    logger.add(sys.stdout, colorize=True, format="<level>{level: <8}</level> | {message}")

    logger.info("=" * 60)
    logger.info("Populate Agencies Table")
    logger.info("=" * 60)

    # Load agencies data
    agencies = load_agencies_yaml(args.source)

    # Get connection string
    connection_string = get_db_connection_string()

    # Populate database
    populate_agencies(agencies, connection_string, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.success("Done!")


if __name__ == "__main__":
    main()
