"""Shared fixtures for managers tests."""

from unittest.mock import MagicMock, patch

import pytest

from data_platform.managers import PostgresManager
from data_platform.managers.dataset_manager import DatasetManager


@pytest.fixture
def pg():
    """PostgresManager with mocked pool and engine (no real DB)."""
    with patch("data_platform.managers.postgres_manager.pool") as mock_pool:
        with patch("data_platform.managers.postgres_manager.create_engine"):
            manager = PostgresManager(connection_string="postgresql://test")
    manager.pool = mock_pool.SimpleConnectionPool.return_value
    manager._engine = MagicMock()
    return manager


@pytest.fixture
def mock_conn(pg):
    """Mock connection from pool."""
    conn = MagicMock()
    pg.pool.getconn.return_value = conn
    return conn


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
