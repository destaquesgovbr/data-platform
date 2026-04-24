"""Shared fixtures for thumbnail_worker tests."""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture()
def _mock_pg():
    """Mock PostgresManager so lifespan doesn't connect to a real DB."""
    with patch("data_platform.workers.thumbnail_worker.app.PostgresManager") as MockPG:
        mock_pg = Mock()
        MockPG.return_value = mock_pg
        yield mock_pg
