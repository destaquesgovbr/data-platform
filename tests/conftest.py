"""
Pytest configuration and fixtures.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from data_platform.managers.dataset_manager import DatasetManager


@pytest.fixture(scope="session", autouse=True)
def set_test_environment():
    """Set testing environment variables."""
    os.environ["TESTING"] = "1"
    os.environ["STORAGE_BACKEND"] = "huggingface"  # Default for tests


@pytest.fixture
def mock_sqlalchemy_engine():
    """Build a mock SQLAlchemy engine that supports `with engine.begin() as conn`."""
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine, mock_conn


@pytest.fixture
def mock_dataset_manager_base():
    """Base fixture: DatasetManager with mocked token."""
    with patch("data_platform.managers.dataset_manager.get_token") as mock_token:
        mock_token.return_value = "hf_test"
        manager = DatasetManager()
        yield manager


@pytest.fixture
def mock_dataset_manager_full():
    """Full fixture: DatasetManager with all methods mocked."""
    with patch("data_platform.managers.dataset_manager.get_token") as mock_token:
        mock_token.return_value = "hf_test"
        with patch.object(DatasetManager, "_load_existing_dataset"):
            with patch.object(DatasetManager, "_push_datasets"):
                with patch.object(DatasetManager, "_sort_dataset", side_effect=lambda ds: ds):
                    manager = DatasetManager()
                    yield manager


