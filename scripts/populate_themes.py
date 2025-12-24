#!/usr/bin/env python3
"""
Populate themes table from hierarchical themes_tree.yaml

This script reads the canonical themes_tree_enriched_full.yaml file and populates
the PostgreSQL themes table with the 3-level hierarchical taxonomy.

Usage:
    python scripts/populate_themes.py
    python scripts/populate_themes.py --source /path/to/themes_tree.yaml
    python scripts/populate_themes.py --dry-run  # Test without inserting
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import psycopg2
import yaml
from loguru import logger


def get_db_connection_string() -> str:
    """Get database connection string from environment or Secret Manager."""
    import subprocess
    import os
    from urllib.parse import quote_plus

    # Get password from Secret Manager
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
        secret_conn_str = result.stdout.strip()

        # Parse password from connection string
        # Format: postgresql://user:password@host:port/db
        # Password may contain special chars including @
        if "://" in secret_conn_str and "@" in secret_conn_str:
            # Extract password (between first : and last @)
            after_protocol = secret_conn_str.split("://")[1]
            # Split from right to handle @ in password
            user_pass, _ = after_protocol.rsplit("@", 1)
            if ":" in user_pass:
                _, password = user_pass.split(":", 1)  # Everything after first :
            else:
                password = "password"
        else:
            password = "password"

    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to fetch connection string from Secret Manager: {e}")
        password = "password"

    # Check if using Cloud SQL Proxy locally
    proxy_check = subprocess.run(
        ["pgrep", "-f", "cloud-sql-proxy"],
        capture_output=True,
    )

    if proxy_check.returncode == 0:
        logger.info("Cloud SQL Proxy detected, using localhost connection")
        # URL-encode the password to handle special characters
        encoded_password = quote_plus(password)
        return f"postgresql://govbrnews_app:{encoded_password}@127.0.0.1:5432/govbrnews"

    # Return original secret for direct connection
    return secret_conn_str


def load_themes_yaml(filepath: Path) -> List[Dict[str, Any]]:
    """Load and parse themes_tree.yaml file."""
    logger.info(f"Loading themes from {filepath}")

    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if "themes" not in data:
        logger.error("Invalid themes file format: missing 'themes' key")
        sys.exit(1)

    return data["themes"]


def flatten_themes(
    themes: List[Dict[str, Any]], level: int = 1, parent_code: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Recursively flatten hierarchical themes into a flat list.

    Each theme will have: code, label, level, parent_code, full_name
    """
    flattened = []

    for theme in themes:
        code = theme["code"]
        label = theme["label"]
        full_name = f"{code} {label}"

        flattened.append(
            {
                "code": code,
                "label": label,
                "full_name": full_name,
                "level": level,
                "parent_code": parent_code,
            }
        )

        # Recursively process children
        if "children" in theme and theme["children"]:
            children_flat = flatten_themes(
                theme["children"], level=level + 1, parent_code=code
            )
            flattened.extend(children_flat)

    return flattened


def populate_themes(
    themes: List[Dict[str, Any]], connection_string: str, dry_run: bool = False
) -> None:
    """Populate themes table with hierarchical data."""
    if dry_run:
        logger.info("DRY RUN MODE - No data will be inserted")

    # Flatten hierarchical structure
    flat_themes = flatten_themes(themes)
    logger.info(f"Found {len(flat_themes)} themes across 3 levels")

    # Count by level
    level_counts = {}
    for theme in flat_themes:
        level = theme["level"]
        level_counts[level] = level_counts.get(level, 0) + 1

    for level, count in sorted(level_counts.items()):
        logger.info(f"  Level {level}: {count} themes")

    if dry_run:
        # Display sample themes
        logger.info("\nSample themes:")
        for theme in flat_themes[:10]:
            logger.info(
                f"  L{theme['level']}: {theme['code']} -> {theme['label']} "
                f"(parent: {theme['parent_code'] or 'None'})"
            )
        logger.info(f"  ... and {len(flat_themes) - 10} more")
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
        # Clear existing data
        logger.info("Clearing existing themes data...")
        cursor.execute("DELETE FROM themes")
        logger.info(f"Deleted {cursor.rowcount} existing records")

        # Insert themes (important: insert parents before children)
        insert_query = """
            INSERT INTO themes (code, label, full_name, level, parent_code)
            VALUES (%s, %s, %s, %s, %s)
        """

        # Sort by level to ensure parents are inserted first
        flat_themes.sort(key=lambda t: t["level"])

        inserted = 0
        for theme in flat_themes:
            cursor.execute(
                insert_query,
                (
                    theme["code"],
                    theme["label"],
                    theme["full_name"],
                    theme["level"],
                    theme["parent_code"],
                ),
            )
            inserted += 1

        # Commit transaction
        conn.commit()
        logger.success(f"✓ Successfully inserted {inserted} themes")

        # Verify
        cursor.execute("SELECT COUNT(*) FROM themes")
        count = cursor.fetchone()[0]
        logger.info(f"Total themes in database: {count}")

        # Show distribution by level
        cursor.execute(
            "SELECT level, COUNT(*) FROM themes GROUP BY level ORDER BY level"
        )
        logger.info("Distribution by level:")
        for level, count in cursor.fetchall():
            logger.info(f"  Level {level}: {count} themes")

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
        description="Populate themes table from themes_tree.yaml"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("../themes/themes_tree_enriched_full.yaml"),
        help="Path to themes file (default: ../themes/themes_tree_enriched_full.yaml)",
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
    logger.info("Populate Themes Table")
    logger.info("=" * 60)

    # Load themes data
    themes = load_themes_yaml(args.source)

    # Get connection string
    connection_string = get_db_connection_string()

    # Populate database
    populate_themes(themes, connection_string, dry_run=args.dry_run)

    logger.info("=" * 60)
    logger.success("Done!")


if __name__ == "__main__":
    main()
