"""
Integration tests for the database migration system.

Validates that all migrations can run sequentially against a real PostgreSQL
database, are idempotent (safe to re-execute), and support rollback.

Requires: PostgreSQL with pgvector extension (docker compose up).
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
MIGRATE_SCRIPT = SCRIPTS_DIR / "migrate.py"
MIGRATIONS_DIR = SCRIPTS_DIR / "migrations"

DATABASE_URL = os.getenv(
    "MIGRATION_TEST_DATABASE_URL",
    "postgresql://test:test@localhost:5432/test_migrations",
)


def _find_concurrent_migrations() -> set[str]:
    """Detect migrations that use CONCURRENTLY (incompatible with transactions)."""
    versions = set()
    for f in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"):
        if "_rollback" in f.name:
            continue
        content = f.read_text()
        if "CONCURRENTLY" in content:
            versions.add(f.name[:3])
    return versions


# Migrations that use CREATE INDEX CONCURRENTLY cannot run inside a transaction.
# The runner wraps each migration in a transaction, so these must be applied manually.
CONCURRENT_MIGRATIONS = _find_concurrent_migrations()

BASELINE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agencies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100),
    parent_key VARCHAR(100),
    url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS themes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    label VARCHAR(500) NOT NULL,
    full_name VARCHAR(600),
    level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    unique_id VARCHAR(32) UNIQUE NOT NULL,
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    theme_l1_id INTEGER REFERENCES themes(id),
    theme_l2_id INTEGER REFERENCES themes(id),
    theme_l3_id INTEGER REFERENCES themes(id),
    most_specific_theme_id INTEGER REFERENCES themes(id),
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    video_url TEXT,
    category VARCHAR(500),
    tags TEXT[],
    content TEXT,
    editorial_lead TEXT,
    subtitle TEXT,
    summary TEXT,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime TIMESTAMP WITH TIME ZONE,
    extracted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    agency_key VARCHAR(100),
    agency_name VARCHAR(500)
);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_news_unique_id ON news(unique_id);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_agency_id ON news(agency_id);
CREATE INDEX IF NOT EXISTS idx_news_agency_key ON news(agency_key);

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(20) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""


def _run_migrate(*args: str, needs_db: bool = True) -> subprocess.CompletedProcess:
    """Run the migrate.py script with given arguments."""
    cmd = [sys.executable, str(MIGRATE_SCRIPT), *args]
    if needs_db:
        cmd.extend(["--db-url", DATABASE_URL])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _apply_concurrent_migration(version: str):
    """Apply a CONCURRENTLY migration outside a transaction, then stamp it."""
    migration_file = next(MIGRATIONS_DIR.glob(f"{version}_*.sql"))
    sql = migration_file.read_text()
    # Remove CONCURRENTLY keyword so it can run in normal mode for testing
    sql_without_concurrent = sql.replace(" CONCURRENTLY", "")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql_without_concurrent)
    cur.close()
    conn.close()

    _run_migrate("stamp", version, "--yes")


def _reset_database():
    """Drop and recreate the test database schema."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    cur.close()
    conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(BASELINE_SQL)
    conn.commit()
    cur.close()
    conn.close()


@pytest.fixture(autouse=True)
def fresh_database():
    """Reset database to baseline state before each test."""
    _reset_database()
    yield


def _apply_all_migrations():
    """Apply all migrations, handling CONCURRENTLY ones specially."""
    if not CONCURRENT_MIGRATIONS:
        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Migration failed:\n{result.stdout}\n{result.stderr}"
        return

    # Find the first CONCURRENTLY migration to determine target
    sorted_concurrent = sorted(CONCURRENT_MIGRATIONS)
    first_concurrent = sorted_concurrent[0]
    # Apply everything before the first CONCURRENTLY migration
    before_target = f"{int(first_concurrent) - 1:03d}"
    result = _run_migrate("migrate", "--target", before_target, "--yes")
    assert result.returncode == 0, f"Migration failed:\n{result.stdout}\n{result.stderr}"

    # Apply each CONCURRENTLY migration manually
    for version in sorted_concurrent:
        _apply_concurrent_migration(version)

    # Apply remaining migrations
    result = _run_migrate("migrate", "--yes")
    if result.returncode != 0:
        assert (
            "No pending migrations" in result.stdout or result.returncode == 0
        ), f"Migration failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.integration
class TestMigrationSequence:
    """Test full migration sequence on a real database."""

    def test_full_sequence_on_clean_db(self):
        """All migrations run without error on baseline schema."""
        _apply_all_migrations()

        result = _run_migrate("status")
        assert result.returncode == 0
        assert "Pending: 0" in result.stdout

    def test_status_shows_zero_pending_after_migrate(self):
        """After applying all migrations, status shows nothing pending."""
        _apply_all_migrations()

        result = _run_migrate("status")
        assert result.returncode == 0
        assert "Pending: 0" in result.stdout

    def test_idempotency_double_run(self):
        """Running migrate twice is safe — second run is a no-op."""
        _apply_all_migrations()

        second = _run_migrate("migrate", "--yes")
        assert second.returncode == 0
        assert "No pending migrations" in second.stdout

    def test_validate_after_full_sequence(self):
        """Validate passes after all migrations are applied."""
        _apply_all_migrations()

        result = _run_migrate("validate", needs_db=False)
        assert result.returncode == 0
        assert "consistent" in result.stdout

    def test_rollback_last_and_reapply(self):
        """Rollback of last non-concurrent migration + re-apply works."""
        _apply_all_migrations()

        # Find the last non-CONCURRENTLY migration with a rollback file
        all_migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*"))
        candidates = [
            m
            for m in all_migrations
            if m.name[:3] not in CONCURRENT_MIGRATIONS
            and not m.name.endswith("_rollback.sql")
            and not m.suffix == ".py"
        ]
        rollback_target = None
        for m in reversed(candidates):
            version = m.name[:3]
            if list(MIGRATIONS_DIR.glob(f"{version}_*_rollback.sql")):
                rollback_target = version
                break

        if not rollback_target:
            pytest.skip("No non-concurrent SQL migration with rollback file found")

        result = _run_migrate("rollback", rollback_target, "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0
        assert "migration(s) processed" in result.stdout

    def test_stamp_then_migrate(self):
        """Stamp first N migrations, then migrate applies only the rest."""
        result = _run_migrate("stamp", "007", "--yes")
        assert result.returncode == 0
        assert "stamped" in result.stdout.lower()

        # Apply remaining (handling CONCURRENTLY ones)
        if CONCURRENT_MIGRATIONS:
            for version in sorted(CONCURRENT_MIGRATIONS):
                if int(version) > 7:
                    # Apply up to before the concurrent migration
                    before = f"{int(version) - 1:03d}"
                    _run_migrate("migrate", "--target", before, "--yes")
                    _apply_concurrent_migration(version)
            _run_migrate("migrate", "--yes")
        else:
            result = _run_migrate("migrate", "--yes")
            assert result.returncode == 0

        result = _run_migrate("status")
        assert "Pending: 0" in result.stdout
