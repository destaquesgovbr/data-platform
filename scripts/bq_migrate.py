#!/usr/bin/env python3
"""
BigQuery migration runner for destaquesgovbr/data-platform.

Forward-only SQL migrations for BigQuery tables. Tracks applied migrations
in a _migration_history table within the dgb_gold dataset.

Usage:
    python scripts/bq_migrate.py status
    python scripts/bq_migrate.py migrate [--dry-run]
    python scripts/bq_migrate.py history
    python scripts/bq_migrate.py validate
"""

import argparse
import getpass
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "bigquery" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_(.+)\.sql$")

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "inspire-7-finep")
DATASET_ID = "dgb_gold"
HISTORY_TABLE = f"{DATASET_ID}._migration_history"

CREATE_HISTORY_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT_ID}.{HISTORY_TABLE}` (
  version STRING NOT NULL,
  name STRING NOT NULL,
  status STRING NOT NULL,
  applied_at TIMESTAMP NOT NULL,
  applied_by STRING,
  duration_ms INT64,
  error_message STRING
)
"""


def discover_migrations() -> list[dict[str, Any]]:
    """Discover migration files sorted by version."""
    migrations = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = MIGRATION_PATTERN.match(f.name)
        if match:
            migrations.append({
                "version": match.group(1),
                "name": match.group(2),
                "path": f,
            })
    return migrations


def get_bigquery_client():
    """Get authenticated BigQuery client."""
    from google.cloud import bigquery
    return bigquery.Client(project=PROJECT_ID)


def ensure_history_table(client) -> None:
    """Create migration history table if it doesn't exist."""
    client.query(CREATE_HISTORY_TABLE_SQL).result()


def get_applied_versions(client) -> set[str]:
    """Get set of successfully applied migration versions."""
    query = f"SELECT DISTINCT version FROM `{PROJECT_ID}.{HISTORY_TABLE}` WHERE status = 'success'"
    try:
        rows = client.query(query).result()
        return {row.version for row in rows}
    except Exception:
        return set()


def record_migration(client, version: str, name: str, status: str,
                     duration_ms: int, error_message: str | None = None) -> None:
    """Record migration execution in history table."""
    query = f"""
    INSERT INTO `{PROJECT_ID}.{HISTORY_TABLE}`
    (version, name, status, applied_at, applied_by, duration_ms, error_message)
    VALUES (@version, @name, @status, @applied_at, @applied_by, @duration_ms, @error_message)
    """
    from google.cloud import bigquery
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("version", "STRING", version),
            bigquery.ScalarQueryParameter("name", "STRING", name),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("applied_at", "TIMESTAMP",
                                          datetime.now(timezone.utc).isoformat()),
            bigquery.ScalarQueryParameter("applied_by", "STRING", getpass.getuser()),
            bigquery.ScalarQueryParameter("duration_ms", "INT64", duration_ms),
            bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
        ]
    )
    client.query(query, job_config=job_config).result()


def cmd_status(client) -> None:
    """Show pending and applied migrations."""
    ensure_history_table(client)
    applied = get_applied_versions(client)
    migrations = discover_migrations()

    print(f"BigQuery Migrations — {PROJECT_ID}.{DATASET_ID}")
    print(f"{'=' * 60}")
    print()

    pending = []
    for m in migrations:
        status = "applied" if m["version"] in applied else "PENDING"
        marker = "  " if status == "applied" else ">>"
        print(f"  {marker} [{m['version']}] {m['name']} — {status}")
        if status == "PENDING":
            pending.append(m)

    print()
    if pending:
        print(f"{len(pending)} pending migration(s)")
    else:
        print("All migrations applied.")


def cmd_migrate(client, dry_run: bool = False) -> None:
    """Apply pending migrations."""
    ensure_history_table(client)
    applied = get_applied_versions(client)
    migrations = discover_migrations()

    pending = [m for m in migrations if m["version"] not in applied]
    if not pending:
        print("No pending migrations.")
        return

    print(f"{'[DRY RUN] ' if dry_run else ''}Applying {len(pending)} migration(s):\n")

    for m in pending:
        sql = m["path"].read_text()
        print(f"  [{m['version']}] {m['name']}")

        if dry_run:
            print(f"    SQL: {sql.strip()[:100]}...")
            print("    (skipped — dry run)")
            continue

        start = time.time()
        try:
            client.query(sql).result()
            duration_ms = int((time.time() - start) * 1000)
            record_migration(client, m["version"], m["name"], "success", duration_ms)
            print(f"    Applied ({duration_ms}ms)")
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            record_migration(client, m["version"], m["name"], "failed", duration_ms, str(e))
            print(f"    FAILED: {e}")
            sys.exit(1)

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Done.")


def cmd_history(client) -> None:
    """Show migration history."""
    ensure_history_table(client)
    query = f"""
    SELECT version, name, status, applied_at, applied_by, duration_ms
    FROM `{PROJECT_ID}.{HISTORY_TABLE}`
    ORDER BY applied_at DESC
    LIMIT 20
    """
    rows = list(client.query(query).result())
    if not rows:
        print("No migration history.")
        return

    print(f"{'Version':<8} {'Name':<40} {'Status':<8} {'Applied At':<20} {'By':<10} {'ms'}")
    print("-" * 100)
    for row in rows:
        print(
            f"{row.version:<8} {row.name:<40} {row.status:<8} "
            f"{row.applied_at.strftime('%Y-%m-%d %H:%M'):<20} "
            f"{(row.applied_by or ''):<10} {row.duration_ms or ''}"
        )


def cmd_validate() -> None:
    """Validate migration files without connecting to BigQuery."""
    migrations = discover_migrations()
    errors = []

    for m in migrations:
        sql = m["path"].read_text()
        if not sql.strip():
            errors.append(f"[{m['version']}] Empty migration file")
        if "DROP TABLE" in sql.upper() and "IF EXISTS" not in sql.upper():
            errors.append(f"[{m['version']}] DROP TABLE without IF EXISTS")

    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Validated {len(migrations)} migration(s) — all OK.")


def main():
    parser = argparse.ArgumentParser(description="BigQuery migration runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show migration status")

    migrate_parser = subparsers.add_parser("migrate", help="Apply pending migrations")
    migrate_parser.add_argument("--dry-run", action="store_true", help="Preview without applying")

    subparsers.add_parser("history", help="Show migration history")
    subparsers.add_parser("validate", help="Validate migration files (offline)")

    args = parser.parse_args()

    if args.command == "validate":
        cmd_validate()
        return

    client = get_bigquery_client()

    if args.command == "status":
        cmd_status(client)
    elif args.command == "migrate":
        cmd_migrate(client, dry_run=args.dry_run)
    elif args.command == "history":
        cmd_history(client)


if __name__ == "__main__":
    main()
