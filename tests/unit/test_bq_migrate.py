"""Unit tests for BigQuery migration runner."""

import re
from pathlib import Path

import pytest


MIGRATIONS_DIR = Path(__file__).parents[2] / "scripts" / "bigquery" / "migrations"
BQ_MIGRATE_SCRIPT = Path(__file__).parents[2] / "scripts" / "bq_migrate.py"


class TestMigrationDiscovery:
    """Tests for discovering and parsing migration files."""

    def test_migrations_dir_exists(self):
        assert MIGRATIONS_DIR.is_dir()

    def test_first_migration_exists(self):
        first = MIGRATIONS_DIR / "001_add_content_hash_to_fato_noticias.sql"
        assert first.is_file()

    def test_migration_files_follow_naming_convention(self):
        pattern = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")
        for f in MIGRATIONS_DIR.glob("*.sql"):
            assert pattern.match(f.name), f"Invalid migration name: {f.name}"

    def test_migration_files_are_valid_sql(self):
        for f in MIGRATIONS_DIR.glob("*.sql"):
            content = f.read_text()
            assert len(content.strip()) > 0, f"Empty migration: {f.name}"
            assert ";" in content or content.strip().endswith("STRING"), (
                f"Migration missing statement terminator: {f.name}"
            )


class TestBqMigrateModule:
    """Tests for bq_migrate.py module."""

    def test_script_exists(self):
        assert BQ_MIGRATE_SCRIPT.is_file()

    def test_can_import_discover_migrations(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("bq_migrate", BQ_MIGRATE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "discover_migrations")

    def test_discover_migrations_returns_sorted_list(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("bq_migrate", BQ_MIGRATE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        migrations = mod.discover_migrations()
        assert len(migrations) >= 1
        assert migrations[0]["version"] == "001"
        assert "content_hash" in migrations[0]["name"]
        assert migrations[0]["path"].exists()

    def test_discover_migrations_sorted_by_version(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("bq_migrate", BQ_MIGRATE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        migrations = mod.discover_migrations()
        versions = [m["version"] for m in migrations]
        assert versions == sorted(versions)
