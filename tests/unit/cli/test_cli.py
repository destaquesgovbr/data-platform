"""
Unit tests for CLI commands.
"""

from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from data_platform.cli import app


runner = CliRunner()


class TestSyncTypesenseCommand:
    """Tests for sync-typesense command."""

    @patch("data_platform.jobs.typesense.sync_to_typesense")
    def test_sync_with_start_date(self, mock_sync):
        """Sync with start date."""
        mock_sync.return_value = {
            "total_fetched": 100,
            "total_indexed": 100,
            "errors": 0,
        }

        result = runner.invoke(app, ["sync-typesense", "--start-date", "2024-01-01"])

        assert result.exit_code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["start_date"] == "2024-01-01"

    @patch("data_platform.jobs.typesense.sync_to_typesense")
    def test_sync_with_date_range(self, mock_sync):
        """Sync with start and end date."""
        mock_sync.return_value = {
            "total_fetched": 50,
            "total_indexed": 50,
            "errors": 0,
        }

        result = runner.invoke(
            app,
            [
                "sync-typesense",
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-01-31",
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["end_date"] == "2024-01-31"

    @patch("data_platform.jobs.typesense.sync_to_typesense")
    def test_sync_full_mode(self, mock_sync):
        """Sync with --full-sync flag."""
        mock_sync.return_value = {
            "total_fetched": 1000,
            "total_indexed": 1000,
            "errors": 0,
        }

        result = runner.invoke(
            app,
            [
                "sync-typesense",
                "--start-date",
                "2024-01-01",
                "--full-sync",
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["full_sync"] is True

    @patch("data_platform.jobs.typesense.sync_to_typesense")
    def test_sync_with_max_records(self, mock_sync):
        """Sync with --max-records option."""
        mock_sync.return_value = {
            "total_fetched": 10,
            "total_indexed": 10,
            "errors": 0,
        }

        result = runner.invoke(
            app,
            [
                "sync-typesense",
                "--start-date",
                "2024-01-01",
                "--max-records",
                "10",
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_sync.call_args[1]
        assert call_kwargs["limit"] == 10

    def test_sync_missing_start_date_fails(self):
        """Sync without --start-date fails."""
        result = runner.invoke(app, ["sync-typesense"])

        assert result.exit_code != 0


class TestTypesenseDeleteCommand:
    """Tests for typesense-delete command."""

    @patch("data_platform.jobs.typesense.delete_typesense_collection")
    def test_delete_with_confirm(self, mock_delete):
        """Delete with --confirm flag."""
        mock_delete.return_value = True

        result = runner.invoke(app, ["typesense-delete", "--confirm"])

        assert result.exit_code == 0
        mock_delete.assert_called_once_with(collection_name="news", confirm=True)

    @patch("data_platform.jobs.typesense.delete_typesense_collection")
    def test_delete_without_confirm_calls_function_with_confirm_false(self, mock_delete):
        """Without --confirm, delete_typesense_collection is called with confirm=False."""
        mock_delete.return_value = False

        result = runner.invoke(app, ["typesense-delete"])

        assert result.exit_code == 0
        mock_delete.assert_called_once_with(collection_name="news", confirm=False)


class TestTypesenseListCommand:
    """Tests for typesense-list command."""

    @patch("data_platform.jobs.typesense.list_typesense_collections")
    def test_list_shows_collections(self, mock_list):
        """List calls list_typesense_collections and exits successfully."""
        mock_list.return_value = [
            {"name": "news", "num_documents": 100},
            {"name": "archive", "num_documents": 50},
        ]

        result = runner.invoke(app, ["typesense-list"])

        assert result.exit_code == 0
        mock_list.assert_called_once()

    @patch("data_platform.jobs.typesense.list_typesense_collections")
    def test_list_empty_collections(self, mock_list):
        """List with no collections exits successfully."""
        mock_list.return_value = []

        result = runner.invoke(app, ["typesense-list"])

        assert result.exit_code == 0
        mock_list.assert_called_once()


# Note: migrate command tests deferred - requires refactoring cli.py to be testable
