"""Unit tests for migrate_unique_ids.py script."""

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Add scripts/ to path so we can import the migration module
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from migrate_unique_ids import (
    build_id_mapping,
    check_collisions,
    dry_run,
    generate_readable_unique_id,
    generate_suffix,
    has_news_features_table,
    rollback,
    slugify,
)


# ---------------------------------------------------------------------------
# TestSlugifyInline
# ---------------------------------------------------------------------------
class TestSlugifyInline:
    def test_basic_ascii(self):
        assert slugify("Hello World") == "hello-world"

    def test_portuguese_accents(self):
        assert slugify("Governo anuncia programa de habitação popular") == (
            "governo-anuncia-programa-de-habitacao-popular"
        )

    def test_special_characters(self):
        assert slugify("R$ 100,00 — crédito & mais!") == "r-100-00-credito-mais"

    def test_max_length_truncates_at_word_boundary(self):
        result = slugify("a" * 50 + "-" + "b" * 50 + "-ccc", max_length=100)
        assert len(result) <= 100
        assert not result.endswith("-")

    def test_empty_string(self):
        assert slugify("") == ""

    def test_only_special_chars(self):
        assert slugify("!@#$%") == ""


# ---------------------------------------------------------------------------
# TestGenerateSuffixInline
# ---------------------------------------------------------------------------
class TestGenerateSuffixInline:
    def test_deterministic(self):
        a = generate_suffix("mec", "2024-01-15", "Test Title")
        b = generate_suffix("mec", "2024-01-15", "Test Title")
        assert a == b

    def test_length_6(self):
        result = generate_suffix("mec", "2024-01-15", "Test Title")
        assert len(result) == 6

    def test_hex_chars_only(self):
        result = generate_suffix("mec", "2024-01-15", "Test Title")
        assert all(c in "0123456789abcdef" for c in result)

    def test_varies_with_agency(self):
        a = generate_suffix("mec", "2024-01-15", "Test Title")
        b = generate_suffix("saude", "2024-01-15", "Test Title")
        assert a != b

    def test_varies_with_date(self):
        a = generate_suffix("mec", "2024-01-15", "Test Title")
        b = generate_suffix("mec", "2024-01-16", "Test Title")
        assert a != b

    def test_varies_with_title(self):
        a = generate_suffix("mec", "2024-01-15", "Title A")
        b = generate_suffix("mec", "2024-01-15", "Title B")
        assert a != b


# ---------------------------------------------------------------------------
# TestGenerateReadableUniqueIdInline
# ---------------------------------------------------------------------------
class TestGenerateReadableUniqueIdInline:
    def test_format_slug_underscore_suffix(self):
        result = generate_readable_unique_id("mec", "2024-01-15", "Test Title")
        parts = result.rsplit("_", 1)
        assert len(parts) == 2
        assert parts[0] == "test-title"
        assert len(parts[1]) == 6

    def test_empty_title_returns_sem_titulo(self):
        result = generate_readable_unique_id("mec", "2024-01-15", "")
        assert result.startswith("sem-titulo_")

    def test_matches_scraper_output(self):
        """Inline functions must produce identical output to the canonical scraper module."""
        scraper_path = Path(__file__).parent.parent.parent.parent / "scraper"
        scraper_module = scraper_path / "src" / "govbr_scraper" / "scrapers" / "unique_id.py"
        if not scraper_module.exists():
            pytest.skip("Scraper repo not available locally")

        sys.path.insert(0, str(scraper_path / "src"))
        try:
            from govbr_scraper.scrapers.unique_id import (
                generate_readable_unique_id as scraper_fn,
            )

            test_cases = [
                ("mec", "2024-01-15", "Governo anuncia novo programa"),
                ("saude", "2025-06-30", "SUS amplia atendimento"),
                ("secom", "2026-03-10", ""),
                ("mec", "2024-01-15", "Título com acentuação: é, ã, ç, ü"),
            ]
            for agency, date, title in test_cases:
                assert generate_readable_unique_id(agency, date, title) == scraper_fn(
                    agency, date, title
                ), f"Mismatch for ({agency}, {date}, {title!r})"
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# TestBuildIdMapping
# ---------------------------------------------------------------------------
class TestBuildIdMapping:
    def _make_row(self, unique_id, agency_key, published_at, title, legacy=None):
        return (unique_id, agency_key, published_at, title, legacy)

    def test_builds_correct_mapping(self):
        rows = [
            self._make_row("abc123hash", "mec", "2024-01-15", "Test Title"),
        ]
        mapping = build_id_mapping(rows)
        expected_new = generate_readable_unique_id("mec", "2024-01-15", "Test Title")
        assert mapping == {"abc123hash": expected_new}

    def test_skips_already_migrated_rows(self):
        new_id = generate_readable_unique_id("mec", "2024-01-15", "Test Title")
        rows = [
            self._make_row(new_id, "mec", "2024-01-15", "Test Title"),
        ]
        mapping = build_id_mapping(rows)
        assert mapping == {}

    def test_no_duplicate_new_ids(self):
        rows = [
            self._make_row(f"hash{i:04d}", "secom", f"2024-01-{i+1:02d}", f"Title {i}")
            for i in range(100)
        ]
        mapping = build_id_mapping(rows)
        new_ids = list(mapping.values())
        assert len(new_ids) == len(set(new_ids))

    def test_detects_collision_via_check(self):
        """If two rows map to the same new_id, check_collisions catches it."""
        mapping = {"old1": "same-slug_abc123", "old2": "same-slug_abc123"}
        collisions = check_collisions(mapping)
        assert len(collisions) > 0


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------
class TestDryRun:
    def test_writes_csv_with_correct_headers(self, tmp_path):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("abc123hash00000000000000000000ff", "mec", "2024-01-15", "Test Title", None),
        ]

        output = tmp_path / "mapping.csv"
        dry_run(mock_conn, str(output))

        with open(output) as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ["old_unique_id", "new_unique_id"]

    def test_csv_row_count_matches_input(self, tmp_path):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("hash1aaa00000000000000000000000a", "mec", "2024-01-15", "Title 1", None),
            ("hash2bbb00000000000000000000000b", "saude", "2024-01-16", "Title 2", None),
            ("hash3ccc00000000000000000000000c", "secom", "2024-01-17", "Title 3", None),
        ]

        output = tmp_path / "mapping.csv"
        dry_run(mock_conn, str(output))

        with open(output) as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
            assert len(rows) == 3

    def test_no_db_writes(self, tmp_path):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("abc123hash00000000000000000000ff", "mec", "2024-01-15", "Test Title", None),
        ]

        output = tmp_path / "mapping.csv"
        dry_run(mock_conn, str(output))

        # cursor.execute should only be called for SELECT (fetch_all_news)
        for c in mock_cursor.execute.call_args_list:
            sql = c[0][0].strip().upper()
            assert not sql.startswith("UPDATE"), "dry_run must not issue UPDATE"
            assert not sql.startswith("ALTER"), "dry_run must not issue ALTER"
            assert not sql.startswith("DROP"), "dry_run must not issue DROP"

        mock_conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# TestRollback
# ---------------------------------------------------------------------------
class TestRollback:
    def test_generates_update_restoring_legacy_ids(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # has_news_features_table returns False (simpler case)
        mock_cursor.fetchone.side_effect = [
            (0,),    # count of rows with NULL legacy_unique_id
            (5,),    # count of rows to rollback
            (False,),  # has_news_features_table
            (0,),    # verification: count of mismatched rows
        ]
        mock_cursor.fetchall.return_value = []

        rollback(mock_conn, batch_size=1000)

        # Should have committed
        mock_conn.commit.assert_called_once()

    def test_handles_news_features_table(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.side_effect = [
            (0,),       # count of rows with NULL legacy_unique_id
            (5,),       # count of rows to rollback
            (True,),    # has_news_features_table
            ("news_features_unique_id_fkey",),  # FK constraint name
            (0,),       # verification
        ]
        mock_cursor.fetchall.return_value = []

        rollback(mock_conn, batch_size=1000)

        # Verify DROP and ADD CONSTRAINT were called
        executed_sqls = [c[0][0] for c in mock_cursor.execute.call_args_list]
        drop_calls = [s for s in executed_sqls if "DROP CONSTRAINT" in s]
        add_calls = [s for s in executed_sqls if "ADD CONSTRAINT" in s]
        assert len(drop_calls) >= 1, "Should DROP FK constraint"
        assert len(add_calls) >= 1, "Should re-ADD FK constraint"

        mock_conn.commit.assert_called_once()
