"""Unit tests for scripts/migrations/006_migrate_unique_ids.py — Python migration interface."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts/migrations to path for importing
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "migrations"))


def _import_migration_006():
    """Import the migration module dynamically (numeric prefix not importable directly)."""
    import importlib.util

    module_path = (
        Path(__file__).parent.parent.parent / "scripts" / "migrations" / "006_migrate_unique_ids.py"
    )
    spec = importlib.util.spec_from_file_location("migration_006", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------
class TestMigration006Interface:
    def test_describe_returns_nonempty_string(self):
        mod = _import_migration_006()
        result = mod.describe()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_has_migrate_function(self):
        mod = _import_migration_006()
        assert callable(getattr(mod, "migrate", None))

    def test_has_rollback_function(self):
        mod = _import_migration_006()
        assert callable(getattr(mod, "rollback", None))


# ---------------------------------------------------------------------------
# ID generation functions (preserved from original)
# ---------------------------------------------------------------------------
class TestSlugify006:
    def test_basic_ascii(self):
        mod = _import_migration_006()
        assert mod.slugify("Hello World") == "hello-world"

    def test_portuguese_accents(self):
        mod = _import_migration_006()
        assert mod.slugify("Governo anuncia programa de habitacao popular") == (
            "governo-anuncia-programa-de-habitacao-popular"
        )

    def test_special_characters(self):
        mod = _import_migration_006()
        assert mod.slugify("R$ 100,00 — credito & mais!") == "r-100-00-credito-mais"

    def test_max_length_truncates(self):
        mod = _import_migration_006()
        result = mod.slugify("a" * 50 + "-" + "b" * 50 + "-ccc", max_length=100)
        assert len(result) <= 100

    def test_empty_string(self):
        mod = _import_migration_006()
        assert mod.slugify("") == ""


class TestGenerateSuffix006:
    def test_deterministic(self):
        mod = _import_migration_006()
        a = mod.generate_suffix("mec", "2024-01-15", "Test Title")
        b = mod.generate_suffix("mec", "2024-01-15", "Test Title")
        assert a == b

    def test_length_6_hex(self):
        mod = _import_migration_006()
        result = mod.generate_suffix("mec", "2024-01-15", "Test Title")
        assert len(result) == 6
        assert all(c in "0123456789abcdef" for c in result)


class TestGenerateReadableUniqueId006:
    def test_format(self):
        mod = _import_migration_006()
        result = mod.generate_readable_unique_id("mec", "2024-01-15", "Test Title")
        parts = result.rsplit("_", 1)
        assert len(parts) == 2
        assert parts[0] == "test-title"
        assert len(parts[1]) == 6

    def test_empty_title(self):
        mod = _import_migration_006()
        result = mod.generate_readable_unique_id("mec", "2024-01-15", "")
        assert result.startswith("sem-titulo_")


# ---------------------------------------------------------------------------
# migrate() and rollback()
# ---------------------------------------------------------------------------
class TestMigrate006:
    @patch("psycopg2.extras.execute_batch")
    def test_migrate_returns_dict_with_rows_affected(self, mock_execute_batch):
        mod = _import_migration_006()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # fetch_all_news returns rows
        mock_cursor.fetchall.return_value = [
            ("abc123hash00000000000000000000ff", "mec", "2024-01-15", "Test Title", None),
        ]
        mock_cursor.fetchone.side_effect = [
            (True,),   # has_news_features_table
            ("news_features_unique_id_fkey",),  # FK name
        ]

        result = mod.migrate(mock_conn, dry_run=False)
        assert isinstance(result, dict)
        assert "rows_migrated" in result
        assert result["rows_migrated"] == 1

    def test_dry_run_does_not_commit(self):
        mod = _import_migration_006()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("abc123hash00000000000000000000ff", "mec", "2024-01-15", "Test Title", None),
        ]

        result = mod.migrate(mock_conn, dry_run=True)
        assert isinstance(result, dict)
        mock_conn.commit.assert_not_called()

    def test_rollback_returns_dict(self):
        mod = _import_migration_006()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (0,),     # null legacy count
            (5,),     # rows to rollback
            (True,),  # has_news_features_table
            ("news_features_unique_id_fkey",),  # FK name
            (0,),     # verification
        ]

        result = mod.rollback(mock_conn, dry_run=False)
        assert isinstance(result, dict)
        assert "rows_rolled_back" in result

    def test_rollback_dry_run_does_not_commit(self):
        mod = _import_migration_006()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (0,),     # null legacy count
            (5,),     # rows to rollback
        ]

        result = mod.rollback(mock_conn, dry_run=True)
        assert isinstance(result, dict)
        mock_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Parity with original script
# ---------------------------------------------------------------------------
class TestParity:
    def test_matches_original_slugify(self):
        """006 slugify must match the original migrate_unique_ids.py output."""
        mod = _import_migration_006()
        # Same test cases as test_migrate_unique_ids.py
        assert mod.slugify("Hello World") == "hello-world"
        assert mod.slugify("R$ 100,00 — credito & mais!") == "r-100-00-credito-mais"
        assert mod.slugify("") == ""

    def test_matches_original_generate_readable_unique_id(self):
        mod = _import_migration_006()
        # These must produce identical output to the original script
        result = mod.generate_readable_unique_id("mec", "2024-01-15", "Governo anuncia novo programa")
        assert "_" in result
        parts = result.rsplit("_", 1)
        assert len(parts[1]) == 6
