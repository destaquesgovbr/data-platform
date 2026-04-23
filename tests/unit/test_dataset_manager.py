"""
Unit tests for DatasetManager (HuggingFace integration).

These tests mock HuggingFace Hub calls to test logic without network access.
"""

from collections import OrderedDict
from unittest.mock import MagicMock, Mock, patch
from pathlib import Path

import pandas as pd
import pytest
from datasets import Dataset
from datasets.exceptions import DatasetNotFoundError

from data_platform.managers.dataset_manager import DatasetManager


class TestDatasetManagerInit:
    """Tests for DatasetManager initialization."""

    @patch("data_platform.managers.dataset_manager.get_token")
    @patch.dict("os.environ", {"HF_TOKEN": "hf_test_token"})
    def test_init_with_env_token(self, mock_get_token):
        """Initialize with token from env var."""
        mock_get_token.return_value = None
        manager = DatasetManager()
        assert manager.token == "hf_test_token"

    @patch("data_platform.managers.dataset_manager.get_token")
    def test_init_with_cli_token(self, mock_get_token):
        """Initialize with token from HF CLI."""
        mock_get_token.return_value = "hf_cli_token"
        manager = DatasetManager()
        assert manager.token == "hf_cli_token"

    @patch("data_platform.managers.dataset_manager.get_token")
    @patch.dict("os.environ", {}, clear=True)
    def test_init_without_token_raises_error(self, mock_get_token):
        """Raise ValueError when no token available."""
        mock_get_token.return_value = None

        with pytest.raises(ValueError, match="authentication token is missing"):
            DatasetManager()


class TestDatasetManagerInsert:
    """Tests for insert() method."""

    def test_insert_into_empty_dataset(self, mock_dataset_manager_full):
        """Insert into empty dataset creates new dataset."""
        mock_dataset_manager_full._load_existing_dataset.return_value = None

        new_data = OrderedDict(
            {
                "unique_id": ["abc123"],
                "title": ["Test News"],
                "published_at": ["2024-01-01"],
                "agency": ["mec"],
            }
        )

        with patch(
            "data_platform.managers.dataset_manager.Dataset.from_dict"
        ) as mock_from_dict:
            mock_dataset = MagicMock()
            mock_from_dict.return_value = mock_dataset

            mock_dataset_manager_full.insert(new_data)

            mock_from_dict.assert_called_once_with(new_data)
            mock_dataset_manager_full._push_datasets.assert_called_once()

    def test_insert_with_allow_update_false(self, mock_dataset_manager_full):
        """Insert with allow_update=False passes correct flag to _merge_new_into_dataset."""
        existing = Dataset.from_dict(
            {
                "unique_id": ["abc123"],
                "title": ["Old Title"],
                "agency": ["mec"],
                "published_at": ["2024-01-01"],
            }
        )
        mock_dataset_manager_full._load_existing_dataset.return_value = existing

        new_data = OrderedDict(
            {
                "unique_id": ["abc123", "def456"],
                "title": ["New Title", "Another News"],
                "agency": ["mec", "saude"],
                "published_at": ["2024-01-01", "2024-01-02"],
            }
        )

        with patch.object(mock_dataset_manager_full, "_merge_new_into_dataset") as mock_merge:
            mock_merge.return_value = existing

            mock_dataset_manager_full.insert(new_data, allow_update=False)

            mock_merge.assert_called_once()
            assert mock_merge.call_args[1]["allow_update"] is False

    def test_insert_with_allow_update_true(self, mock_dataset_manager_full):
        """Insert with allow_update=True passes correct flag to _merge_new_into_dataset."""
        existing = Dataset.from_dict(
            {
                "unique_id": ["abc123"],
                "title": ["Old Title"],
                "agency": ["mec"],
                "published_at": ["2024-01-01"],
            }
        )
        mock_dataset_manager_full._load_existing_dataset.return_value = existing

        new_data = OrderedDict(
            {
                "unique_id": ["abc123"],
                "title": ["Updated Title"],
                "agency": ["mec"],
                "published_at": ["2024-01-01"],
            }
        )

        with patch.object(mock_dataset_manager_full, "_merge_new_into_dataset") as mock_merge:
            mock_merge.return_value = existing

            mock_dataset_manager_full.insert(new_data, allow_update=True)

            assert mock_merge.call_args[1]["allow_update"] is True


class TestDatasetManagerUpdate:
    """Tests for update() method."""

    def test_update_nonexistent_dataset_returns_early(self, mock_dataset_manager_full):
        """Update on non-existent dataset returns early."""
        mock_dataset_manager_full._load_existing_dataset.return_value = None

        df = pd.DataFrame({"unique_id": ["abc123"], "title": ["Updated"]})

        # Should not raise, just log and return
        mock_dataset_manager_full.update(df)

        mock_dataset_manager_full._push_datasets.assert_not_called()

    def test_update_applies_changes(self, mock_dataset_manager_full):
        """Update applies changes to existing rows."""
        existing = Dataset.from_dict(
            {
                "unique_id": ["abc123"],
                "title": ["Old Title"],
                "agency": ["mec"],
                "published_at": ["2024-01-01"],
            }
        )
        mock_dataset_manager_full._load_existing_dataset.return_value = existing

        df = pd.DataFrame(
            {
                "unique_id": ["abc123"],
                "title": ["Updated Title"],
            }
        )

        with patch.object(mock_dataset_manager_full, "_apply_updates") as mock_apply:
            mock_apply.return_value = existing

            mock_dataset_manager_full.update(df)

            mock_apply.assert_called_once()
            mock_dataset_manager_full._push_datasets.assert_called_once()


class TestDatasetManagerGet:
    """Tests for get() method."""

    def test_get_with_date_range(self, mock_dataset_manager_base):
        """Get filters by date range."""
        dataset = Dataset.from_dict(
            {
                "unique_id": ["abc", "def", "ghi"],
                "published_at": ["2024-01-01", "2024-01-15", "2024-02-01"],
                "agency": ["mec", "mec", "saude"],
            }
        )

        with patch.object(mock_dataset_manager_base, "_load_existing_dataset") as mock_load:
            mock_load.return_value = dataset

            result = mock_dataset_manager_base.get("2024-01-01", "2024-01-20")

            assert len(result) == 2
            assert "abc" in result["unique_id"].values
            assert "def" in result["unique_id"].values

    def test_get_with_agency_filter(self, mock_dataset_manager_base):
        """Get filters by agency."""
        dataset = Dataset.from_dict(
            {
                "unique_id": ["abc", "def"],
                "published_at": ["2024-01-01", "2024-01-01"],
                "agency": ["mec", "saude"],
            }
        )

        with patch.object(mock_dataset_manager_base, "_load_existing_dataset") as mock_load:
            mock_load.return_value = dataset

            result = mock_dataset_manager_base.get("2024-01-01", "2024-01-31", agency="mec")

            assert len(result) == 1
            assert result.iloc[0]["unique_id"] == "abc"

    def test_get_empty_dataset_returns_empty_df(self, mock_dataset_manager_base):
        """Get on empty dataset returns empty DataFrame."""
        with patch.object(mock_dataset_manager_base, "_load_existing_dataset") as mock_load:
            mock_load.return_value = None

            result = mock_dataset_manager_base.get("2024-01-01", "2024-01-31")

            assert isinstance(result, pd.DataFrame)
            assert len(result) == 0


class TestDatasetManagerLoadExisting:
    """Tests for _load_existing_dataset() method."""

    @patch("data_platform.managers.dataset_manager.load_dataset")
    @patch("data_platform.managers.dataset_manager.shutil.rmtree")
    @patch("data_platform.managers.dataset_manager.Path.home")
    def test_load_clears_cache(self, mock_home, mock_rmtree, mock_load, mock_dataset_manager_base):
        """Load clears HF cache before loading."""
        mock_home.return_value = Path("/fake/home")
        mock_dataset = MagicMock()
        mock_load.return_value = mock_dataset

        with patch.object(Path, "exists", return_value=True):
            result = mock_dataset_manager_base._load_existing_dataset()

            mock_rmtree.assert_called_once()
            mock_load.assert_called_once()

    @patch("data_platform.managers.dataset_manager.load_dataset")
    def test_load_returns_none_on_not_found(self, mock_load, mock_dataset_manager_base):
        """Load returns None when dataset not found."""
        mock_load.side_effect = DatasetNotFoundError("Not found")

        result = mock_dataset_manager_base._load_existing_dataset()

        assert result is None


class TestDatasetManagerErrorHandling:
    """Tests for error handling scenarios."""

    def test_network_error_on_load(self, mock_dataset_manager_base):
        """Network error during load propagates."""
        with patch.object(mock_dataset_manager_base, "_load_existing_dataset") as mock_load:
            mock_load.side_effect = ConnectionError("Network unreachable")

            with pytest.raises(ConnectionError):
                mock_dataset_manager_base.get("2024-01-01", "2024-01-31")

    def test_push_error_propagates(self, mock_dataset_manager_base):
        """Push error propagates to caller."""
        mock_dataset_manager_base._load_existing_dataset = MagicMock(return_value=None)
        mock_dataset = MagicMock(spec=Dataset)

        with patch.object(mock_dataset_manager_base, "_push_datasets") as mock_push, \
             patch.object(mock_dataset_manager_base, "_sort_dataset", return_value=mock_dataset), \
             patch("data_platform.managers.dataset_manager.Dataset.from_dict",
                   return_value=mock_dataset):

            mock_push.side_effect = Exception("Hub API error")

            new_data = OrderedDict(
                {
                    "unique_id": ["abc"],
                    "title": ["Test"],
                    "agency": ["mec"],
                    "published_at": ["2024-01-01"],
                }
            )

            with pytest.raises(Exception, match="Hub API error"):
                mock_dataset_manager_base.insert(new_data)
