#!/usr/bin/env python3
"""
Generic database migration runner for destaquesgovbr/data-platform.

Supports SQL (.sql) and Python (.py) migrations discovered by naming convention.
Provides audit history, dry-run, rollback, and validation.

Usage:
    python scripts/migrate.py status
    python scripts/migrate.py migrate [--dry-run] [--target VERSION]
    python scripts/migrate.py rollback VERSION [--dry-run]
    python scripts/migrate.py history
    python scripts/migrate.py validate
"""

import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIGRATION_PATTERN = re.compile(r"^(\d{3})_(.+)\.(sql|py)$")
ROLLBACK_SUFFIX = "_rollback.sql"

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

CREATE_MIGRATION_HISTORY_SQL = """
CREATE TABLE IF NOT EXISTS migration_history (
    id              SERIAL PRIMARY KEY,
    version         VARCHAR(10)  NOT NULL,
    name            VARCHAR(255) NOT NULL,
    migration_type  VARCHAR(10)  NOT NULL CHECK (migration_type IN ('sql', 'python')),
    operation       VARCHAR(10)  NOT NULL CHECK (operation IN ('migrate', 'rollback', 'dry_run')),
    status          VARCHAR(20)  NOT NULL CHECK (status IN ('success', 'failed', 'unavailable')),
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    applied_by      TEXT NOT NULL,
    run_id          TEXT,
    description     TEXT,
    execution_details JSONB,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_mh_version    ON migration_history(version);
CREATE INDEX IF NOT EXISTS idx_mh_started_at ON migration_history(started_at DESC);
"""

CREATE_MIGRATION_STATUS_VIEW_SQL = """
CREATE OR REPLACE VIEW migration_status AS
SELECT DISTINCT ON (version)
    version, name, migration_type, operation, status, applied_by, started_at, duration_ms
FROM migration_history
WHERE status = 'success'
ORDER BY version, started_at DESC;
"""

TABLE_EXISTS_SQL = """
SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = %s
)
"""

IMPORT_SCHEMA_VERSION_SQL = """
INSERT INTO migration_history (version, name, migration_type, operation, status, applied_by, description)
SELECT
    sv.version,
    'schema_version_import',
    'sql',
    'migrate',
    'success',
    'bootstrap',
    sv.description
FROM schema_version sv
WHERE NOT EXISTS (
    SELECT 1 FROM migration_history mh
    WHERE mh.applied_by = 'bootstrap' AND mh.version = sv.version
)
"""

RECORD_HISTORY_SQL = """
INSERT INTO migration_history
    (version, name, migration_type, operation, status, started_at, finished_at,
     duration_ms, applied_by, run_id, description, execution_details, error_message)
VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s)
"""

GET_APPLIED_VERSIONS_SQL = """
SELECT DISTINCT version FROM migration_status WHERE operation = 'migrate'
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MigrationInfo:
    version: str
    name: str
    path: Path
    migration_type: str  # 'sql' or 'python'
    rollback_path: Path | None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_migrations(migrations_dir: Path) -> list[MigrationInfo]:
    """Discover migration files in a directory by naming convention."""
    if not migrations_dir.exists():
        return []

    migrations = {}
    rollbacks = {}

    for f in sorted(migrations_dir.iterdir()):
        name = f.name

        # Collect rollback files separately
        if name.endswith(ROLLBACK_SUFFIX):
            match = re.match(r"^(\d{3})_", name)
            if match:
                rollbacks[match.group(1)] = f
            continue

        match = MIGRATION_PATTERN.match(name)
        if match:
            version = match.group(1)
            desc = match.group(2)
            mtype = "python" if match.group(3) == "py" else "sql"
            migrations[version] = MigrationInfo(
                version=version,
                name=desc,
                path=f,
                migration_type=mtype,
                rollback_path=None,
            )

    # Associate rollback files
    for version, rollback_path in rollbacks.items():
        if version in migrations:
            migrations[version].rollback_path = rollback_path

    return sorted(migrations.values(), key=lambda m: m.version)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap(conn) -> None:
    """Create migration_history table and import schema_version if present."""
    cursor = conn.cursor()
    try:
        # Check if migration_history already exists
        cursor.execute(TABLE_EXISTS_SQL, ("migration_history",))
        exists = cursor.fetchone()[0]
        if exists:
            return

        # Create table and view
        cursor.execute(CREATE_MIGRATION_HISTORY_SQL)
        cursor.execute(CREATE_MIGRATION_STATUS_VIEW_SQL)

        # Import from schema_version if it exists
        cursor.execute(TABLE_EXISTS_SQL, ("schema_version",))
        sv_exists = cursor.fetchone()[0]
        if sv_exists:
            cursor.execute(IMPORT_SCHEMA_VERSION_SQL)
            logger.info("Imported schema_version entries into migration_history")

        conn.commit()
        logger.info("Bootstrap complete: migration_history table created")
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Status / Pending
# ---------------------------------------------------------------------------

def get_pending(
    conn, migrations: list[MigrationInfo], target: str | None = None
) -> list[MigrationInfo]:
    """Return migrations that haven't been applied yet."""
    cursor = conn.cursor()
    try:
        cursor.execute(GET_APPLIED_VERSIONS_SQL)
        applied = {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()

    pending = [m for m in migrations if m.version not in applied]

    if target:
        pending = [m for m in pending if m.version <= target]

    return pending


# ---------------------------------------------------------------------------
# Record history
# ---------------------------------------------------------------------------

def _record_history(
    conn,
    migration: MigrationInfo,
    operation: str,
    status: str,
    started_at: float,
    applied_by: str,
    run_id: str | None,
    description: str | None = None,
    execution_details: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Insert a record into migration_history."""
    duration_ms = int((time.time() - started_at) * 1000)
    cursor = conn.cursor()
    try:
        from datetime import datetime, timezone

        started_dt = datetime.fromtimestamp(started_at, tz=timezone.utc)
        cursor.execute(
            RECORD_HISTORY_SQL,
            (
                migration.version,
                migration.name,
                migration.migration_type,
                operation,
                status,
                started_dt,
                duration_ms,
                applied_by,
                run_id,
                description,
                json.dumps(execution_details) if execution_details else None,
                error_message,
            ),
        )
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Execute migration
# ---------------------------------------------------------------------------

def _load_python_module(path: Path):
    """Dynamically load a Python migration module."""
    module_name = f"migration_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute_migration(
    conn,
    migration: MigrationInfo,
    dry_run: bool,
    applied_by: str,
    run_id: str | None,
) -> None:
    """Execute a single migration (SQL or Python) with atomic commit."""
    operation = "dry_run" if dry_run else "migrate"
    started_at = time.time()
    description = None
    execution_details = None

    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Executing {migration.version}_{migration.name} ({migration.migration_type})")

    try:
        if migration.migration_type == "sql":
            sql_content = migration.path.read_text()
            cursor = conn.cursor()
            try:
                cursor.execute(sql_content)
            finally:
                cursor.close()
        else:
            # Python migration
            module = _load_python_module(migration.path)
            if not hasattr(module, "describe"):
                raise AttributeError(
                    f"Python migration {migration.path.name} must define describe()"
                )
            description = module.describe()
            result = module.migrate(conn, dry_run=dry_run)
            execution_details = result if isinstance(result, dict) else None

        if dry_run:
            _record_history(
                conn, migration, operation, "success", started_at,
                applied_by, run_id, description, execution_details,
            )
            conn.rollback()
            logger.info(f"[DRY RUN] {migration.version} previewed (rolled back)")
        else:
            _record_history(
                conn, migration, operation, "success", started_at,
                applied_by, run_id, description, execution_details,
            )
            conn.commit()
            logger.info(f"{migration.version}_{migration.name} applied successfully")

    except Exception as e:
        conn.rollback()
        # Record failure in a separate transaction
        try:
            _record_history(
                conn, migration, operation, "failed", started_at,
                applied_by, run_id, description, error_message=str(e),
            )
            conn.commit()
        except Exception:
            logger.warning("Could not record failure in migration_history")
        raise


# ---------------------------------------------------------------------------
# Execute rollback
# ---------------------------------------------------------------------------

def execute_rollback(
    conn,
    migration: MigrationInfo,
    dry_run: bool,
    applied_by: str,
    run_id: str | None,
) -> None:
    """Execute rollback for a single migration."""
    operation = "rollback"
    started_at = time.time()
    description = None
    execution_details = None

    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Rolling back {migration.version}_{migration.name}")

    try:
        if migration.migration_type == "sql":
            if not migration.rollback_path or not migration.rollback_path.exists():
                raise FileNotFoundError(
                    f"No rollback file for SQL migration {migration.version}_{migration.name}. "
                    f"Expected: {migration.version}_{migration.name}_rollback.sql"
                )
            sql_content = migration.rollback_path.read_text()
            cursor = conn.cursor()
            try:
                cursor.execute(sql_content)
            finally:
                cursor.close()
        else:
            # Python migration
            module = _load_python_module(migration.path)
            try:
                result = module.rollback(conn, dry_run=dry_run)
                execution_details = result if isinstance(result, dict) else None
            except NotImplementedError as nie:
                _record_history(
                    conn, migration, operation, "unavailable", started_at,
                    applied_by, run_id, description,
                    error_message=str(nie),
                )
                conn.commit()
                logger.warning(f"{migration.version} rollback unavailable: {nie}")
                return

        if dry_run:
            conn.rollback()
            logger.info(f"[DRY RUN] {migration.version} rollback previewed")
        else:
            _record_history(
                conn, migration, operation, "success", started_at,
                applied_by, run_id, description, execution_details,
            )
            conn.commit()
            logger.info(f"{migration.version}_{migration.name} rolled back successfully")

    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        conn.rollback()
        try:
            _record_history(
                conn, migration, operation, "failed", started_at,
                applied_by, run_id, description, error_message=str(e),
            )
            conn.commit()
        except Exception:
            logger.warning("Could not record rollback failure in migration_history")
        raise


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

def validate_migrations(migrations: list[MigrationInfo]) -> list[str]:
    """Check for sequence gaps and other issues."""
    issues = []
    if not migrations:
        return issues

    versions = [int(m.version) for m in migrations]
    for i in range(len(versions) - 1):
        if versions[i + 1] - versions[i] > 1:
            for gap in range(versions[i] + 1, versions[i + 1]):
                issues.append(f"Sequence gap: migration {gap:03d} is missing")

    return issues


# ---------------------------------------------------------------------------
# CLI (typer)
# ---------------------------------------------------------------------------

def _get_applied_by() -> str:
    """Determine who is running the migration."""
    return os.getenv("GITHUB_ACTOR", os.getenv("USER", "unknown"))


def _get_run_id() -> str | None:
    """Get GitHub Actions run ID if available."""
    return os.getenv("GITHUB_RUN_ID")


def main():
    try:
        import typer
    except ImportError:
        print("typer is required. Install with: pip install typer")
        sys.exit(1)

    app = typer.Typer(help="Database migration runner for destaquesgovbr/data-platform")

    def _connect(db_url: str):
        import psycopg2

        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        return conn

    @app.command()
    def status(
        db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
        migrations_path: str = typer.Option(str(MIGRATIONS_DIR), "--migrations-dir"),
    ):
        """Show status of all migrations."""
        conn = _connect(db_url)
        try:
            bootstrap(conn)
            migrations = discover_migrations(Path(migrations_path))
            pending = get_pending(conn, migrations)
            applied = [m for m in migrations if m not in pending]

            typer.echo(f"Total migrations: {len(migrations)}")
            typer.echo(f"Applied: {len(applied)}")
            typer.echo(f"Pending: {len(pending)}")
            typer.echo("")
            for m in migrations:
                marker = "PENDING" if m in pending else "APPLIED"
                typer.echo(f"  [{marker}] {m.version}_{m.name} ({m.migration_type})")
        finally:
            conn.close()

    @app.command(name="migrate")
    def migrate_cmd(
        db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
        migrations_path: str = typer.Option(str(MIGRATIONS_DIR), "--migrations-dir"),
        dry_run: bool = typer.Option(False, "--dry-run"),
        target: str = typer.Option(None, "--target"),
        yes: bool = typer.Option(False, "--yes", "-y"),
    ):
        """Apply pending migrations."""
        conn = _connect(db_url)
        try:
            bootstrap(conn)
            migrations = discover_migrations(Path(migrations_path))
            pending = get_pending(conn, migrations, target=target)

            if not pending:
                typer.echo("No pending migrations.")
                return

            typer.echo(f"Pending migrations ({len(pending)}):")
            for m in pending:
                typer.echo(f"  {m.version}_{m.name} ({m.migration_type})")

            if not dry_run and not yes:
                typer.confirm("Apply these migrations?", abort=True)

            applied_by = _get_applied_by()
            run_id = _get_run_id()

            for m in pending:
                execute_migration(conn, m, dry_run=dry_run, applied_by=applied_by, run_id=run_id)

            typer.echo(f"\n{'[DRY RUN] ' if dry_run else ''}Done: {len(pending)} migration(s) processed.")
        finally:
            conn.close()

    @app.command()
    def rollback(
        version: str = typer.Argument(..., help="Migration version to rollback (e.g. 006)"),
        db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
        migrations_path: str = typer.Option(str(MIGRATIONS_DIR), "--migrations-dir"),
        dry_run: bool = typer.Option(False, "--dry-run"),
        yes: bool = typer.Option(False, "--yes", "-y"),
    ):
        """Rollback a specific migration."""
        conn = _connect(db_url)
        try:
            bootstrap(conn)
            migrations = discover_migrations(Path(migrations_path))
            target = next((m for m in migrations if m.version == version), None)
            if not target:
                typer.echo(f"Migration {version} not found.")
                raise typer.Exit(1)

            if not dry_run and not yes:
                typer.confirm(f"Rollback migration {version}_{target.name}?", abort=True)

            applied_by = _get_applied_by()
            run_id = _get_run_id()
            execute_rollback(conn, target, dry_run=dry_run, applied_by=applied_by, run_id=run_id)

            typer.echo(f"\n{'[DRY RUN] ' if dry_run else ''}Rollback of {version} complete.")
        finally:
            conn.close()

    @app.command()
    def history(
        db_url: str = typer.Option(None, "--db-url", envvar="DATABASE_URL"),
        limit: int = typer.Option(20, "--limit"),
    ):
        """Show migration history."""
        conn = _connect(db_url)
        try:
            bootstrap(conn)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT version, name, migration_type, operation, status, "
                "applied_by, started_at, duration_ms, error_message "
                "FROM migration_history ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                typer.echo("No migration history.")
                return

            typer.echo(f"{'Ver':>5} {'Name':<30} {'Type':<8} {'Op':<10} {'Status':<12} {'By':<15} {'Duration':>10}")
            typer.echo("-" * 95)
            for row in rows:
                ver, name, mtype, op, st, by, at, dur, err = row
                dur_str = f"{dur}ms" if dur else "-"
                typer.echo(f"{ver:>5} {name:<30} {mtype:<8} {op:<10} {st:<12} {by:<15} {dur_str:>10}")
                if err:
                    typer.echo(f"      Error: {err[:80]}")
        finally:
            conn.close()

    @app.command()
    def validate(
        migrations_path: str = typer.Option(str(MIGRATIONS_DIR), "--migrations-dir"),
    ):
        """Validate migration files for consistency."""
        migrations = discover_migrations(Path(migrations_path))
        issues = validate_migrations(migrations)

        if issues:
            typer.echo(f"Found {len(issues)} issue(s):")
            for issue in issues:
                typer.echo(f"  - {issue}")
            raise typer.Exit(1)
        else:
            typer.echo(f"All {len(migrations)} migrations are consistent.")

    app()


if __name__ == "__main__":
    main()
