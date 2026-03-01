"""
Unit tests for PostgresManager feature store methods.

Tests upsert_features, get_features, and get_features_batch with mocked database.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from data_platform.managers import PostgresManager


@pytest.fixture
def manager():
    """Create a PostgresManager with mocked pool."""
    with patch("data_platform.managers.postgres_manager.pool"):
        mgr = PostgresManager(connection_string="postgresql://test")
        yield mgr


@pytest.fixture
def mock_conn(manager):
    """Mock connection from pool."""
    conn = MagicMock()
    manager.pool.getconn.return_value = conn
    return conn


class TestUpsertFeatures:
    """Tests for upsert_features method."""

    def test_upsert_features_insert(self, manager, mock_conn):
        """First insert creates a new row."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        result = manager.upsert_features("abc123", {"word_count": 150})

        assert result is True
        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO news_features" in sql
        assert "ON CONFLICT" in sql
        assert "features || EXCLUDED.features" in sql
        mock_conn.commit.assert_called_once()

    def test_upsert_features_merge(self, manager, mock_conn):
        """Merge preserves existing features via || operator."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        result = manager.upsert_features("abc123", {"has_image": True, "sentiment": {"score": 0.8}})

        assert result is True
        params = cursor.execute.call_args[0][1]
        assert params[0] == "abc123"

    def test_upsert_features_empty_dict_returns_false(self, manager, mock_conn):
        """Empty features dict is a no-op."""
        result = manager.upsert_features("abc123", {})

        assert result is False
        mock_conn.cursor.assert_not_called()

    def test_upsert_features_rollback_on_error(self, manager, mock_conn):
        """Database error triggers rollback."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            manager.upsert_features("abc123", {"word_count": 100})

        mock_conn.rollback.assert_called_once()

    def test_upsert_features_connection_returned(self, manager, mock_conn):
        """Connection is always returned to pool."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        manager.upsert_features("abc123", {"word_count": 100})

        manager.pool.putconn.assert_called_once_with(mock_conn)


class TestGetFeatures:
    """Tests for get_features method."""

    def test_get_features_existing(self, manager, mock_conn):
        """Returns features dict for existing article."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {"features": {"word_count": 150, "has_image": True}}

        result = manager.get_features("abc123")

        assert result == {"word_count": 150, "has_image": True}
        cursor.execute.assert_called_once()
        assert "abc123" in cursor.execute.call_args[0][1]

    def test_get_features_nonexistent(self, manager, mock_conn):
        """Returns None for non-existent article."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = manager.get_features("nonexistent")

        assert result is None

    def test_get_features_connection_returned(self, manager, mock_conn):
        """Connection is always returned to pool."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        manager.get_features("abc123")

        manager.pool.putconn.assert_called_once_with(mock_conn)


class TestGetFeaturesBatch:
    """Tests for get_features_batch method."""

    def test_get_features_batch(self, manager, mock_conn):
        """Returns features for multiple articles."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {"unique_id": "abc123", "features": {"word_count": 150}},
            {"unique_id": "def456", "features": {"word_count": 200}},
        ]

        result = manager.get_features_batch(["abc123", "def456"])

        assert result == {
            "abc123": {"word_count": 150},
            "def456": {"word_count": 200},
        }
        sql = cursor.execute.call_args[0][0]
        assert "ANY(%s)" in sql

    def test_get_features_batch_partial(self, manager, mock_conn):
        """Missing articles are omitted from result."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {"unique_id": "abc123", "features": {"word_count": 150}},
        ]

        result = manager.get_features_batch(["abc123", "missing"])

        assert "abc123" in result
        assert "missing" not in result

    def test_get_features_batch_empty_list(self, manager, mock_conn):
        """Empty list returns empty dict without DB call."""
        result = manager.get_features_batch([])

        assert result == {}
        mock_conn.cursor.assert_not_called()

    def test_get_features_batch_connection_returned(self, manager, mock_conn):
        """Connection is always returned to pool."""
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []

        manager.get_features_batch(["abc123"])

        manager.pool.putconn.assert_called_once_with(mock_conn)
