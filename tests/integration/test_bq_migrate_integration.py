"""
Integration tests for BigQuery migration runner.

These tests require GCP authentication and BigQuery access.
Run with: pytest tests/integration/test_bq_migrate_integration.py -v

They validate that:
- Migration SQL is syntactically valid against BigQuery
- The history table can be created and queried
- The migrate command applies migrations idempotently
"""

import importlib.util
import os
from pathlib import Path

import pytest

BQ_MIGRATE_SCRIPT = Path(__file__).parents[2] / "scripts" / "bq_migrate.py"
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "inspire-7-finep")


def _load_bq_migrate():
    spec = importlib.util.spec_from_file_location("bq_migrate", BQ_MIGRATE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_bq_client():
    from google.cloud import bigquery

    return bigquery.Client(project=PROJECT_ID)


@pytest.mark.integration
class TestBqMigrateOffline:
    """Tests that validate migration files without BigQuery access."""

    def test_validate_command_passes(self):
        """All migration files pass offline validation."""
        mod = _load_bq_migrate()
        mod.cmd_validate()

    def test_all_migrations_use_idempotent_ddl(self):
        """Migrations should use IF NOT EXISTS / IF EXISTS for safety."""
        mod = _load_bq_migrate()
        migrations = mod.discover_migrations()

        for m in migrations:
            sql = m["path"].read_text().upper()
            has_alter = "ALTER TABLE" in sql
            has_create = "CREATE TABLE" in sql
            has_drop = "DROP" in sql

            if has_alter and "ADD COLUMN" in sql:
                assert "IF NOT EXISTS" in sql, (
                    f"Migration {m['version']}: ALTER TABLE ADD COLUMN should use IF NOT EXISTS"
                )
            if has_create:
                assert "IF NOT EXISTS" in sql, (
                    f"Migration {m['version']}: CREATE TABLE should use IF NOT EXISTS"
                )
            if has_drop:
                assert "IF EXISTS" in sql, (
                    f"Migration {m['version']}: DROP should use IF EXISTS"
                )


@pytest.mark.integration
class TestBqMigrateIntegration:
    """Integration tests that hit BigQuery."""

    @pytest.fixture(autouse=True)
    def _require_bigquery(self):
        """Skip all tests if BigQuery is not accessible."""
        try:
            client = _get_bq_client()
            client.query("SELECT 1").result()
        except Exception as e:
            pytest.skip(f"BigQuery not accessible: {e}")

    def test_history_table_creation(self):
        """ensure_history_table creates _migration_history without error."""
        mod = _load_bq_migrate()
        client = _get_bq_client()
        mod.ensure_history_table(client)

        query = f"SELECT COUNT(*) as cnt FROM `{PROJECT_ID}.dgb_gold._migration_history`"
        result = list(client.query(query).result())[0]
        assert result.cnt >= 0

    def test_get_applied_versions_returns_set(self):
        """get_applied_versions returns a set (possibly empty)."""
        mod = _load_bq_migrate()
        client = _get_bq_client()
        mod.ensure_history_table(client)

        versions = mod.get_applied_versions(client)
        assert isinstance(versions, set)

    def test_migration_sql_is_valid_via_dry_run(self):
        """Each migration file contains valid BigQuery SQL (dry-run validation)."""
        mod = _load_bq_migrate()
        client = _get_bq_client()
        from google.cloud import bigquery

        migrations = mod.discover_migrations()
        assert len(migrations) >= 1

        for m in migrations:
            sql = m["path"].read_text()
            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            try:
                client.query(sql, job_config=job_config)
            except Exception as e:
                error_str = str(e)
                if "Syntax error" in error_str:
                    pytest.fail(f"Migration {m['version']} has syntax error: {e}")

    def test_migrate_is_idempotent(self):
        """Running migrate twice does not fail or duplicate history entries."""
        mod = _load_bq_migrate()
        client = _get_bq_client()
        mod.ensure_history_table(client)

        mod.cmd_migrate(client, dry_run=False)

        query = (
            f"SELECT COUNT(*) as cnt FROM `{PROJECT_ID}.dgb_gold._migration_history` "
            f"WHERE status = 'success'"
        )
        count_after_first = list(client.query(query).result())[0].cnt

        mod.cmd_migrate(client, dry_run=False)

        count_after_second = list(client.query(query).result())[0].cnt
        assert count_after_second == count_after_first

    def test_status_command_runs(self, capsys):
        """status command runs without error."""
        mod = _load_bq_migrate()
        client = _get_bq_client()
        mod.ensure_history_table(client)
        mod.cmd_status(client)

        captured = capsys.readouterr()
        assert "BigQuery Migrations" in captured.out
