"""Unit tests for scripts/migrate.py — generic migration runner."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Add scripts/ to path so we can import the migration runner
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
class TestDiscoverMigrations:
    def test_discovers_sql_and_py_in_order(self, tmp_path):
        (tmp_path / "001_first.sql").write_text("SELECT 1;")
        (tmp_path / "002_second.py").write_text("def migrate(conn, dry_run=False): pass")
        (tmp_path / "003_third.sql").write_text("SELECT 3;")

        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path)
        assert [m.version for m in migrations] == ["001", "002", "003"]
        assert [m.migration_type for m in migrations] == ["sql", "python", "sql"]

    def test_ignores_rollback_files(self, tmp_path):
        (tmp_path / "001_create.sql").write_text("CREATE TABLE t;")
        (tmp_path / "001_create_rollback.sql").write_text("DROP TABLE t;")

        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path)
        assert len(migrations) == 1
        assert migrations[0].version == "001"

    def test_associates_rollback_file(self, tmp_path):
        (tmp_path / "001_create.sql").write_text("CREATE TABLE t;")
        (tmp_path / "001_create_rollback.sql").write_text("DROP TABLE t;")

        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path)
        assert migrations[0].rollback_path is not None
        assert "rollback" in str(migrations[0].rollback_path)

    def test_empty_directory(self, tmp_path):
        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path)
        assert migrations == []

    def test_ignores_non_migration_files(self, tmp_path):
        (tmp_path / "README.md").write_text("# Docs")
        (tmp_path / "helper.py").write_text("x = 1")
        (tmp_path / "001_real.sql").write_text("SELECT 1;")

        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path)
        assert len(migrations) == 1

    def test_nonexistent_directory(self, tmp_path):
        from migrate import discover_migrations

        migrations = discover_migrations(tmp_path / "nonexistent")
        assert migrations == []


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
class TestBootstrap:
    def _mock_conn(self, table_exists=False, schema_version_exists=False, schema_rows=None):
        """Create a mock connection with configurable behavior."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        # fetchone responses for EXISTS checks
        responses = []
        # 1st call: check if migration_history exists
        responses.append((table_exists,))
        if not table_exists:
            # 2nd call: check if schema_version exists
            responses.append((schema_version_exists,))
            if schema_version_exists:
                # fetchall for schema_version rows
                cursor.fetchall.return_value = schema_rows or []

        cursor.fetchone.side_effect = responses
        return conn, cursor

    def test_creates_migration_history_table(self):
        conn, cursor = self._mock_conn(table_exists=False, schema_version_exists=False)

        from migrate import bootstrap

        bootstrap(conn)

        # Should have executed CREATE TABLE
        executed_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        create_calls = [s for s in executed_sqls if "CREATE TABLE" in s and "migration_history" in s]
        assert len(create_calls) >= 1

        conn.commit.assert_called()

    def test_imports_schema_version_entries(self):
        schema_rows = [
            ("1.0", "2024-12-24 14:00:00+00", "Initial schema"),
            ("1.3", "2025-03-10 17:00:00+00", "Alter unique_id"),
        ]
        conn, cursor = self._mock_conn(
            table_exists=False, schema_version_exists=True, schema_rows=schema_rows
        )

        from migrate import bootstrap

        bootstrap(conn)

        # Should have INSERT ... migration_history for each schema_version row
        executed_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        insert_calls = [s for s in executed_sqls if "INSERT" in s and "migration_history" in s]
        assert len(insert_calls) >= 1

    def test_skips_if_already_bootstrapped(self):
        conn, cursor = self._mock_conn(table_exists=True)

        from migrate import bootstrap

        bootstrap(conn)

        # Should NOT execute CREATE TABLE
        executed_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        create_calls = [s for s in executed_sqls if "CREATE TABLE" in s]
        assert len(create_calls) == 0

    def test_works_without_schema_version(self):
        conn, cursor = self._mock_conn(table_exists=False, schema_version_exists=False)

        from migrate import bootstrap

        bootstrap(conn)
        # Should not raise; commit should be called
        conn.commit.assert_called()


# ---------------------------------------------------------------------------
# Get Pending
# ---------------------------------------------------------------------------
class TestGetPending:
    def test_returns_pending_migrations(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        # Already applied: 001
        cursor.fetchall.return_value = [("001",)]

        from migrate import MigrationInfo, get_pending

        migrations = [
            MigrationInfo(version="001", name="first", path=Path("001.sql"), migration_type="sql", rollback_path=None),
            MigrationInfo(version="002", name="second", path=Path("002.sql"), migration_type="sql", rollback_path=None),
            MigrationInfo(version="003", name="third", path=Path("003.py"), migration_type="python", rollback_path=None),
        ]
        pending = get_pending(conn, migrations)
        assert [m.version for m in pending] == ["002", "003"]

    def test_none_pending_when_all_applied(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [("001",), ("002",)]

        from migrate import MigrationInfo, get_pending

        migrations = [
            MigrationInfo(version="001", name="first", path=Path("001.sql"), migration_type="sql", rollback_path=None),
            MigrationInfo(version="002", name="second", path=Path("002.sql"), migration_type="sql", rollback_path=None),
        ]
        pending = get_pending(conn, migrations)
        assert pending == []

    def test_respects_target_version(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []  # none applied

        from migrate import MigrationInfo, get_pending

        migrations = [
            MigrationInfo(version="001", name="first", path=Path("001.sql"), migration_type="sql", rollback_path=None),
            MigrationInfo(version="002", name="second", path=Path("002.sql"), migration_type="sql", rollback_path=None),
            MigrationInfo(version="003", name="third", path=Path("003.sql"), migration_type="sql", rollback_path=None),
        ]
        pending = get_pending(conn, migrations, target="002")
        assert [m.version for m in pending] == ["001", "002"]


# ---------------------------------------------------------------------------
# Execute Migration (SQL)
# ---------------------------------------------------------------------------
class TestExecuteMigrationSQL:
    def test_executes_sql_and_records_history(self, tmp_path):
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("CREATE TABLE test_table (id INT);")

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.autocommit = False

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="test", path=sql_file,
            migration_type="sql", rollback_path=None,
        )
        execute_migration(conn, migration, dry_run=False, applied_by="test", run_id=None)

        # SQL content should have been executed
        executed_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        sql_calls = [s for s in executed_sqls if "CREATE TABLE test_table" in s]
        assert len(sql_calls) >= 1

        # History should have been recorded
        history_calls = [s for s in executed_sqls if "migration_history" in s]
        assert len(history_calls) >= 1

        conn.commit.assert_called()

    def test_dry_run_does_not_commit(self, tmp_path):
        sql_file = tmp_path / "001_test.sql"
        sql_file.write_text("CREATE TABLE test_table (id INT);")

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="test", path=sql_file,
            migration_type="sql", rollback_path=None,
        )
        execute_migration(conn, migration, dry_run=True, applied_by="test", run_id=None)

        conn.commit.assert_not_called()
        conn.rollback.assert_called()

    def test_failure_records_failed_status(self, tmp_path):
        sql_file = tmp_path / "001_bad.sql"
        sql_file.write_text("INVALID SQL;")

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        # Make SQL execution fail
        execute_calls = [0]

        def side_effect(sql, *args, **kwargs):
            execute_calls[0] += 1
            if execute_calls[0] == 1:  # First execute is the migration SQL
                raise Exception("syntax error")

        cursor.execute.side_effect = side_effect

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="bad", path=sql_file,
            migration_type="sql", rollback_path=None,
        )
        with pytest.raises(Exception, match="syntax error"):
            execute_migration(conn, migration, dry_run=False, applied_by="test", run_id=None)

        conn.rollback.assert_called()


# ---------------------------------------------------------------------------
# Execute Migration (Python)
# ---------------------------------------------------------------------------
class TestExecuteMigrationPython:
    def test_imports_and_calls_migrate(self, tmp_path):
        py_file = tmp_path / "001_test_migration.py"
        py_file.write_text(
            'def describe(): return "Test migration"\n'
            'def migrate(conn, dry_run=False): return {"rows_affected": 42}\n'
            'def rollback(conn, dry_run=False): return {}\n'
        )

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="test_migration", path=py_file,
            migration_type="python", rollback_path=None,
        )
        execute_migration(conn, migration, dry_run=False, applied_by="test", run_id=None)
        conn.commit.assert_called()

    def test_stores_execution_details(self, tmp_path):
        py_file = tmp_path / "001_test_migration.py"
        py_file.write_text(
            'def describe(): return "Test"\n'
            'def migrate(conn, dry_run=False): return {"rows_affected": 42, "collisions": 0}\n'
            'def rollback(conn, dry_run=False): return {}\n'
        )

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="test_migration", path=py_file,
            migration_type="python", rollback_path=None,
        )
        execute_migration(conn, migration, dry_run=False, applied_by="test", run_id=None)

        # Check that execution_details with rows_affected was passed to INSERT
        executed_sqls = [c for c in cursor.execute.call_args_list]
        history_calls = [c for c in executed_sqls if "migration_history" in str(c)]
        assert len(history_calls) >= 1
        # The JSONB value should contain rows_affected
        history_args = str(history_calls[-1])
        assert "rows_affected" in history_args or "42" in history_args

    def test_module_without_describe_raises(self, tmp_path):
        py_file = tmp_path / "001_bad.py"
        py_file.write_text(
            'def migrate(conn, dry_run=False): return {}\n'
        )

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_migration

        migration = MigrationInfo(
            version="001", name="bad", path=py_file,
            migration_type="python", rollback_path=None,
        )
        with pytest.raises((AttributeError, Exception)):
            execute_migration(conn, migration, dry_run=False, applied_by="test", run_id=None)


# ---------------------------------------------------------------------------
# Execute Rollback
# ---------------------------------------------------------------------------
class TestExecuteRollback:
    def test_sql_rollback_executes_file(self, tmp_path):
        migration_file = tmp_path / "001_create.sql"
        migration_file.write_text("CREATE TABLE t (id INT);")
        rollback_file = tmp_path / "001_create_rollback.sql"
        rollback_file.write_text("DROP TABLE t;")

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_rollback

        migration = MigrationInfo(
            version="001", name="create", path=migration_file,
            migration_type="sql", rollback_path=rollback_file,
        )
        execute_rollback(conn, migration, dry_run=False, applied_by="test", run_id=None)

        executed_sqls = [c[0][0] for c in cursor.execute.call_args_list]
        drop_calls = [s for s in executed_sqls if "DROP TABLE t" in s]
        assert len(drop_calls) >= 1
        conn.commit.assert_called()

    def test_python_rollback_calls_rollback_function(self, tmp_path):
        py_file = tmp_path / "001_data.py"
        py_file.write_text(
            'def describe(): return "Test"\n'
            'def migrate(conn, dry_run=False): return {}\n'
            'def rollback(conn, dry_run=False): return {"restored": 10}\n'
        )

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_rollback

        migration = MigrationInfo(
            version="001", name="data", path=py_file,
            migration_type="python", rollback_path=None,
        )
        execute_rollback(conn, migration, dry_run=False, applied_by="test", run_id=None)
        conn.commit.assert_called()

    def test_sql_rollback_errors_if_no_file(self, tmp_path):
        migration_file = tmp_path / "001_create.sql"
        migration_file.write_text("CREATE TABLE t;")

        conn = MagicMock()

        from migrate import MigrationInfo, execute_rollback

        migration = MigrationInfo(
            version="001", name="create", path=migration_file,
            migration_type="sql", rollback_path=None,
        )
        with pytest.raises((FileNotFoundError, ValueError)):
            execute_rollback(conn, migration, dry_run=False, applied_by="test", run_id=None)

    def test_python_not_implemented_records_unavailable(self, tmp_path):
        py_file = tmp_path / "001_data.py"
        py_file.write_text(
            'def describe(): return "Test"\n'
            'def migrate(conn, dry_run=False): return {}\n'
            'def rollback(conn, dry_run=False): raise NotImplementedError("Cannot rollback")\n'
        )

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_rollback

        migration = MigrationInfo(
            version="001", name="data", path=py_file,
            migration_type="python", rollback_path=None,
        )
        # Should not raise — records unavailable instead
        execute_rollback(conn, migration, dry_run=False, applied_by="test", run_id=None)

        executed_sqls = str(cursor.execute.call_args_list)
        assert "unavailable" in executed_sqls

    def test_rollback_records_operation_in_history(self, tmp_path):
        rollback_file = tmp_path / "001_create_rollback.sql"
        rollback_file.write_text("DROP TABLE t;")
        migration_file = tmp_path / "001_create.sql"
        migration_file.write_text("CREATE TABLE t;")

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        from migrate import MigrationInfo, execute_rollback

        migration = MigrationInfo(
            version="001", name="create", path=migration_file,
            migration_type="sql", rollback_path=rollback_file,
        )
        execute_rollback(conn, migration, dry_run=False, applied_by="test", run_id=None)

        executed_sqls = str(cursor.execute.call_args_list)
        assert "rollback" in executed_sqls
        assert "migration_history" in executed_sqls


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
class TestValidateMigrations:
    def test_detects_sequence_gap(self, tmp_path):
        (tmp_path / "001_first.sql").write_text("SELECT 1;")
        (tmp_path / "003_third.sql").write_text("SELECT 3;")

        from migrate import discover_migrations, validate_migrations

        migrations = discover_migrations(tmp_path)
        issues = validate_migrations(migrations)
        assert any("gap" in issue.lower() or "002" in issue for issue in issues)

    def test_returns_empty_when_consistent(self, tmp_path):
        (tmp_path / "001_first.sql").write_text("SELECT 1;")
        (tmp_path / "002_second.sql").write_text("SELECT 2;")
        (tmp_path / "003_third.sql").write_text("SELECT 3;")

        from migrate import discover_migrations, validate_migrations

        migrations = discover_migrations(tmp_path)
        issues = validate_migrations(migrations)
        assert issues == []
