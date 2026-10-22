"""
Unit tests for CLI commands.
"""

from unittest.mock import patch

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


class TestBqMergeThemeChangesCommand:
    """bq-merge-theme-changes: MERGE do fato_noticias a partir da auditoria do tema 26.

    Contrato de 22/10: lê as duas campanhas (tema26-llm-d1 e tema26-034); sem --campaign.
    """

    ENV = {"DATABASE_URL": "postgresql://ro", "GCP_PROJECT_ID": "projeto-x"}

    @patch("data_platform.jobs.bigquery.theme_changes.merge_theme_changes")
    def test_dry_run_com_as_campanhas_do_contrato(self, mock_merge):
        mock_merge.return_value = {"staged": 1, "fato_rows_to_update": 1, "merged": 0}

        result = runner.invoke(app, ["bq-merge-theme-changes", "--dry-run"], env=self.ENV)

        assert result.exit_code == 0, result.output
        mock_merge.assert_called_once_with(
            "postgresql://ro", "projeto-x", reverted=False, dry_run=True
        )

    @patch("data_platform.jobs.bigquery.theme_changes.merge_theme_changes")
    def test_reverted_depois_do_rollback(self, mock_merge):
        mock_merge.return_value = {"staged": 0, "fato_rows_to_update": 0, "merged": 0}

        result = runner.invoke(app, ["bq-merge-theme-changes", "--reverted"], env=self.ENV)

        assert result.exit_code == 0, result.output
        assert mock_merge.call_args.kwargs == {"reverted": True, "dry_run": False}

    @patch("data_platform.jobs.bigquery.theme_changes.merge_theme_changes")
    def test_sem_opcao_de_campanha(self, mock_merge):
        result = runner.invoke(
            app, ["bq-merge-theme-changes", "--campaign", "tema26-%"], env=self.ENV
        )

        assert result.exit_code != 0
        mock_merge.assert_not_called()

    @patch("data_platform.jobs.bigquery.theme_changes.merge_theme_changes")
    def test_sem_database_url_falha(self, mock_merge):
        result = runner.invoke(
            app, ["bq-merge-theme-changes"], env={"DATABASE_URL": "", "GCP_PROJECT_ID": "p"}
        )

        assert result.exit_code != 0
        mock_merge.assert_not_called()
