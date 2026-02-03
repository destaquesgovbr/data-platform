"""
Unit tests for Typesense sync functionality.

Tests the sync_to_typesense() function and related helpers.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.jobs.typesense.sync_job import (
    _sync_small_dataset,
    sync_to_typesense,
)


class TestSyncToTypesense:
    """Tests for sync_to_typesense function."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def mock_postgres_manager(self) -> Iterator[MagicMock]:
        """Mock PostgresManager class."""
        with patch("data_platform.jobs.typesense.sync_job.PostgresManager") as mock:
            yield mock

    @pytest.fixture  # type: ignore[untyped-decorator]
    def mock_get_client(self) -> Iterator[MagicMock]:
        """Mock get_client function."""
        with patch("data_platform.jobs.typesense.sync_job.get_client") as mock:
            yield mock

    @pytest.fixture  # type: ignore[untyped-decorator]
    def mock_create_collection(self) -> Iterator[MagicMock]:
        """Mock create_collection function."""
        with patch("data_platform.jobs.typesense.sync_job.create_collection") as mock:
            yield mock

    @pytest.fixture  # type: ignore[untyped-decorator]
    def mock_index_documents(self) -> Iterator[MagicMock]:
        """Mock index_documents function."""
        with patch("data_platform.jobs.typesense.sync_job.index_documents") as mock:
            yield mock

    @pytest.fixture  # type: ignore[untyped-decorator]
    def sample_df(self) -> pd.DataFrame:
        """Create sample DataFrame with news data."""
        return pd.DataFrame(
            [
                {
                    "unique_id": "news-1",
                    "title": "Título 1",
                    "agency": "planalto",
                    "published_at_ts": 1705334400,  # 2025-01-15
                    "content_embedding": [0.1, 0.2, 0.3],
                },
                {
                    "unique_id": "news-2",
                    "title": "Título 2",
                    "agency": "planalto",
                    "published_at_ts": 1705420800,  # 2025-01-16
                    "content_embedding": [0.4, 0.5, 0.6],
                },
            ]
        )

    def test_sync_basic_success(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        sample_df: pd.DataFrame,
    ) -> None:
        """Test basic sync with valid date."""
        # Setup mocks
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call function
        result = sync_to_typesense(start_date="2025-01-15", limit=10)

        # Assertions
        assert result["total_fetched"] == 2
        assert result["total_indexed"] == 2
        assert result["errors"] == 0
        assert result["skipped"] is False

        # Verify mocks were called
        mock_postgres_manager.assert_called_once()
        mock_get_client.assert_called_once()
        mock_create_collection.assert_called_once_with(mock_client)
        mock_index_documents.assert_called_once()
        mock_pg.close_all.assert_called_once()

    def test_sync_with_date_range(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        sample_df: pd.DataFrame,
    ) -> None:
        """Test sync with explicit start and end dates."""
        # Setup
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call with date range
        result = sync_to_typesense(
            start_date="2025-01-15",
            end_date="2025-01-20",
            limit=10,
        )

        # Verify
        assert result["total_indexed"] == 2
        mock_pg.get_news_for_typesense.assert_called_once_with(
            start_date="2025-01-15",
            end_date="2025-01-20",
            limit=10,
        )

    def test_sync_empty_dataset(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
    ) -> None:
        """Test sync when no documents exist in date range."""
        # Setup - empty DataFrame
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = pd.DataFrame()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Call
        result = sync_to_typesense(start_date="2025-01-15", limit=10)

        # Verify
        assert result["total_fetched"] == 0
        assert result["total_indexed"] == 0
        assert result["errors"] == 0
        assert result["skipped"] is False

        # index_documents should not be called for empty dataset
        mock_index_documents.assert_not_called()

    def test_sync_full_mode_with_existing_docs(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        sample_df: pd.DataFrame,
    ) -> None:
        """Test full sync mode with existing documents."""
        # Setup
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock existing documents in collection
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"num_documents": 1000}
        mock_client.collections.__getitem__.return_value = mock_collection

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call with full_sync=True
        result = sync_to_typesense(
            start_date="2025-01-15",
            full_sync=True,
            limit=10,
        )

        # Should proceed with upsert (not skip)
        assert result["total_indexed"] == 2
        assert result["skipped"] is False

        # Verify mode is 'full'
        call_kwargs = mock_index_documents.call_args[1]
        assert call_kwargs["mode"] == "full"
        assert call_kwargs["force"] is True

    def test_sync_incremental_mode(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        sample_df: pd.DataFrame,
    ) -> None:
        """Test incremental sync mode (default)."""
        # Setup
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call without full_sync (default is False)
        sync_to_typesense(start_date="2025-01-15", limit=10)

        # Verify mode is 'incremental'
        call_kwargs = mock_index_documents.call_args[1]
        assert call_kwargs["mode"] == "incremental"
        assert call_kwargs["force"] is False

    def test_sync_with_limit(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
    ) -> None:
        """Test sync respects limit parameter."""
        # Setup - create more rows than limit
        large_df = pd.DataFrame(
            [
                {"unique_id": f"news-{i}", "title": f"Título {i}", "published_at_ts": 1705334400}
                for i in range(20)
            ]
        )

        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg
        mock_pg.get_news_for_typesense.return_value = large_df

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_index_documents.return_value = {
            "total_processed": 20,
            "total_indexed": 20,
            "errors": 0,
            "skipped": False,
        }

        # Call with limit
        sync_to_typesense(start_date="2025-01-15", limit=10)

        # Verify limit was passed to PostgresManager
        mock_pg.get_news_for_typesense.assert_called_once()
        call_kwargs = mock_pg.get_news_for_typesense.call_args[1]
        assert call_kwargs["limit"] == 10

    def test_sync_batch_processing(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
    ) -> None:
        """Test sync processes documents in batches for large datasets."""
        # Setup - large dataset that triggers batch processing
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg

        # Create batches to iterate over
        batch1 = pd.DataFrame(
            [
                {"unique_id": f"news-{i}", "title": f"Título {i}", "published_at_ts": 1705334400}
                for i in range(5000)
            ]
        )
        batch2 = pd.DataFrame(
            [
                {"unique_id": f"news-{i}", "title": f"Título {i}", "published_at_ts": 1705334400}
                for i in range(5000, 8000)
            ]
        )

        mock_pg.iter_news_for_typesense.return_value = iter([batch1, batch2])

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock index_documents to return stats for each batch
        mock_index_documents.side_effect = [
            {"total_processed": 5000, "total_indexed": 5000, "errors": 0},
            {"total_processed": 3000, "total_indexed": 3000, "errors": 0},
        ]

        # Call without limit (triggers batch processing)
        result = sync_to_typesense(start_date="2025-01-15")

        # Verify
        assert result["total_fetched"] == 8000
        assert result["total_indexed"] == 8000
        assert result["errors"] == 0

        # Verify index_documents was called twice (once per batch)
        assert mock_index_documents.call_count == 2

    def test_sync_batch_with_errors(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
    ) -> None:
        """Test sync handles errors in batch processing."""
        # Setup
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg

        batch = pd.DataFrame(
            [
                {"unique_id": f"news-{i}", "title": f"Título {i}", "published_at_ts": 1705334400}
                for i in range(5000)
            ]
        )
        mock_pg.iter_news_for_typesense.return_value = iter([batch])

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock index_documents with some errors
        mock_index_documents.return_value = {
            "total_processed": 5000,
            "total_indexed": 4990,
            "errors": 10,
        }

        # Call
        result = sync_to_typesense(start_date="2025-01-15")

        # Verify errors are counted
        assert result["total_fetched"] == 5000
        assert result["total_indexed"] == 4990
        assert result["errors"] == 10

    def test_sync_closes_connection_on_error(
        self,
        mock_postgres_manager: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
    ) -> None:
        """Test that PostgreSQL connection is closed even if error occurs."""
        # Setup
        mock_pg = MagicMock()
        mock_postgres_manager.return_value = mock_pg

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock create_collection to raise error
        mock_create_collection.side_effect = Exception("Connection failed")

        # Call should raise but still close connection
        with pytest.raises(Exception, match="Connection failed"):
            sync_to_typesense(start_date="2025-01-15")

        # Verify close_all was called even after error
        mock_pg.close_all.assert_called_once()


class TestSyncSmallDataset:
    """Tests for _sync_small_dataset helper function."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def mock_index_documents(self) -> Iterator[MagicMock]:
        """Mock index_documents function."""
        with patch("data_platform.jobs.typesense.sync_job.index_documents") as mock:
            yield mock

    @pytest.fixture  # type: ignore[untyped-decorator]
    def sample_df(self) -> pd.DataFrame:
        """Create sample DataFrame."""
        return pd.DataFrame(
            [
                {"unique_id": "news-1", "title": "Título 1", "published_at_ts": 1705334400},
                {"unique_id": "news-2", "title": "Título 2", "published_at_ts": 1705420800},
            ]
        )

    def test_small_dataset_basic(
        self, mock_index_documents: MagicMock, sample_df: pd.DataFrame
    ) -> None:
        """Test syncing small dataset without recreating collection."""
        # Setup
        mock_pg = MagicMock()
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call
        result = _sync_small_dataset(
            pg_manager=mock_pg,
            client=mock_client,
            start_date="2025-01-15",
            end_date="2025-01-15",
            full_sync=False,
            batch_size=1000,
            limit=10,
        )

        # Verify
        assert result["total_fetched"] == 2
        assert result["total_indexed"] == 2
        assert result["errors"] == 0

        # Verify get_news_for_typesense was called with correct params
        mock_pg.get_news_for_typesense.assert_called_once_with(
            start_date="2025-01-15",
            end_date="2025-01-15",
            limit=10,
        )

        # Verify index_documents was called with incremental mode
        mock_index_documents.assert_called_once()
        call_kwargs = mock_index_documents.call_args[1]
        assert call_kwargs["mode"] == "incremental"
        assert call_kwargs["force"] is False

    def test_small_dataset_full_sync_mode(
        self, mock_index_documents: MagicMock, sample_df: pd.DataFrame
    ) -> None:
        """Test small dataset with full_sync mode."""
        # Setup
        mock_pg = MagicMock()
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call with full_sync=True
        _sync_small_dataset(
            pg_manager=mock_pg,
            client=mock_client,
            start_date="2025-01-15",
            end_date="2025-01-15",
            full_sync=True,
            batch_size=1000,
            limit=None,
        )

        # Verify index_documents was called with full mode
        call_kwargs = mock_index_documents.call_args[1]
        assert call_kwargs["mode"] == "full"
        assert call_kwargs["force"] is True

    def test_small_dataset_empty(self, mock_index_documents: MagicMock) -> None:
        """Test small dataset with no results."""
        # Setup - empty DataFrame
        mock_pg = MagicMock()
        mock_pg.get_news_for_typesense.return_value = pd.DataFrame()

        mock_client = MagicMock()

        # Call
        result = _sync_small_dataset(
            pg_manager=mock_pg,
            client=mock_client,
            start_date="2025-01-15",
            end_date="2025-01-15",
            full_sync=False,
            batch_size=1000,
            limit=None,
        )

        # Verify
        assert result["total_fetched"] == 0
        assert result["total_indexed"] == 0
        assert result["errors"] == 0
        assert result["skipped"] is False

        # index_documents should not be called
        mock_index_documents.assert_not_called()

    def test_small_dataset_calculates_published_week(
        self, mock_index_documents: MagicMock, sample_df: pd.DataFrame
    ) -> None:
        """Test that published_week is calculated for documents."""
        # Setup
        mock_pg = MagicMock()
        mock_pg.get_news_for_typesense.return_value = sample_df

        mock_client = MagicMock()

        mock_index_documents.return_value = {
            "total_processed": 2,
            "total_indexed": 2,
            "errors": 0,
            "skipped": False,
        }

        # Call
        _sync_small_dataset(
            pg_manager=mock_pg,
            client=mock_client,
            start_date="2025-01-15",
            end_date="2025-01-15",
            full_sync=False,
            batch_size=1000,
            limit=None,
        )

        # Verify index_documents was called with DataFrame that has published_week
        call_args = mock_index_documents.call_args
        df_passed = call_args[1]["df"]
        assert "published_week" in df_passed.columns
