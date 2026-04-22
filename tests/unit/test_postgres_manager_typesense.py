"""
Unit tests for PostgresManager methods used in the Typesense sync pipeline.

Covers: _build_typesense_query, count_news_for_typesense, get_news_for_typesense,
        iter_news_for_typesense, update, get, get_by_unique_id, count.
"""

from datetime import datetime
from unittest.mock import MagicMock, Mock, call, patch

import pandas as pd
import pytest

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.models import News


@pytest.fixture
def pg():
    """PostgresManager with mocked pool and engine (no real DB)."""
    with patch("data_platform.managers.postgres_manager.pool") as mock_pool:
        with patch("data_platform.managers.postgres_manager.create_engine"):
            manager = PostgresManager(connection_string="postgresql://test")
    manager.pool = mock_pool.SimpleConnectionPool.return_value
    manager._engine = MagicMock()
    return manager


def _make_conn(fetchone_return=None, fetchall_return=None):
    """Build a mock psycopg2 connection + cursor."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_return
    mock_cursor.fetchall.return_value = fetchall_return or []
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = lambda s: mock_cursor
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


class TestBuildTypesenseQuery:
    def test_query_contains_required_columns(self, pg):
        query = pg._build_typesense_query()

        assert "n.unique_id" in query
        assert "n.agency_key as agency" in query
        assert "n.title" in query
        assert "EXTRACT(EPOCH FROM n.published_at)::bigint as published_at_ts" in query
        assert "n.content_embedding" in query

    def test_query_has_theme_joins(self, pg):
        query = pg._build_typesense_query()

        assert "LEFT JOIN themes t1" in query
        assert "LEFT JOIN themes t2" in query
        assert "LEFT JOIN themes t3" in query
        assert "LEFT JOIN news_features nf" in query

    def test_query_includes_feature_fields(self, pg):
        query = pg._build_typesense_query()

        assert "sentiment_label" in query
        assert "word_count" in query
        assert "has_image" in query
        assert "trending_score" in query

    def test_query_returns_string(self, pg):
        result = pg._build_typesense_query()
        assert isinstance(result, str)
        assert len(result) > 100


class TestCountNewsForTypesense:
    def test_returns_count(self, pg):
        mock_conn, mock_cursor = _make_conn(fetchone_return=(42,))
        pg.pool.getconn.return_value = mock_conn

        result = pg.count_news_for_typesense("2024-01-01")

        assert result == 42

    def test_end_date_defaults_to_start_date(self, pg):
        mock_conn, mock_cursor = _make_conn(fetchone_return=(0,))
        pg.pool.getconn.return_value = mock_conn

        pg.count_news_for_typesense("2024-01-15")

        # Both params passed to execute should use same date
        execute_call = mock_cursor.execute.call_args
        params = execute_call[0][1]
        assert params[0] == "2024-01-15"
        assert params[1] == "2024-01-15"

    def test_returns_zero_for_empty_range(self, pg):
        mock_conn, mock_cursor = _make_conn(fetchone_return=(0,))
        pg.pool.getconn.return_value = mock_conn

        result = pg.count_news_for_typesense("2024-01-01", "2024-01-01")

        assert result == 0

    def test_connection_returned_to_pool(self, pg):
        mock_conn, _ = _make_conn(fetchone_return=(5,))
        pg.pool.getconn.return_value = mock_conn

        pg.count_news_for_typesense("2024-01-01")

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGetNewsForTypesense:
    def test_returns_dataframe(self, pg):
        expected_df = pd.DataFrame({"unique_id": ["abc123"], "title": ["Test"]})
        pg._engine.connect = MagicMock()
        pg._engine.__class__ = MagicMock  # satisfy pd.read_sql_query

        with patch("pandas.read_sql_query", return_value=expected_df):
            result = pg.get_news_for_typesense("2024-01-01")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_passes_date_params(self, pg):
        with patch("pandas.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            pg.get_news_for_typesense("2024-01-01", "2024-01-31")

            call_kwargs = mock_read.call_args
            params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][2]
            assert "2024-01-01" in params
            assert "2024-01-31" in params

    def test_applies_limit_when_given(self, pg):
        with patch("pandas.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            pg.get_news_for_typesense("2024-01-01", limit=100)

            call_args = mock_read.call_args
            query = call_args[0][0]
            assert "LIMIT" in query

    def test_no_limit_clause_when_none(self, pg):
        with patch("pandas.read_sql_query", return_value=pd.DataFrame()) as mock_read:
            pg.get_news_for_typesense("2024-01-01")

            call_args = mock_read.call_args
            query = call_args[0][0]
            assert "LIMIT" not in query


class TestIterNewsForTypesense:
    def test_yields_nothing_when_count_zero(self, pg):
        with patch.object(pg, "count_news_for_typesense", return_value=0):
            batches = list(pg.iter_news_for_typesense("2024-01-01"))

        assert batches == []

    def test_yields_single_batch_for_small_dataset(self, pg):
        df = pd.DataFrame({"unique_id": [f"id{i}" for i in range(10)]})

        with patch.object(pg, "count_news_for_typesense", return_value=10):
            with patch("pandas.read_sql_query", return_value=df):
                batches = list(pg.iter_news_for_typesense("2024-01-01", batch_size=1000))

        assert len(batches) == 1
        assert len(batches[0]) == 10

    def test_stops_when_empty_batch_returned(self, pg):
        """If read_sql_query returns empty before total_count is exhausted, stop."""
        with patch.object(pg, "count_news_for_typesense", return_value=100):
            with patch("pandas.read_sql_query", return_value=pd.DataFrame()):
                batches = list(pg.iter_news_for_typesense("2024-01-01", batch_size=1000))

        assert batches == []

    def test_yields_multiple_batches(self, pg):
        batch = pd.DataFrame({"unique_id": [f"id{i}" for i in range(5)]})

        call_count = 0

        def read_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return batch if call_count <= 2 else pd.DataFrame()

        with patch.object(pg, "count_news_for_typesense", return_value=10):
            with patch("pandas.read_sql_query", side_effect=read_side_effect):
                batches = list(pg.iter_news_for_typesense("2024-01-01", batch_size=5))

        assert len(batches) == 2


class TestUpdate:
    def test_update_returns_true_when_found(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.update("abc123", {"title": "New Title"})

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_update_returns_false_when_not_found(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.update("missing_id", {"title": "New Title"})

        assert result is False

    def test_update_empty_dict_raises(self, pg):
        with pytest.raises(ValueError, match="Updates dictionary cannot be empty"):
            pg.update("abc123", {})

    def test_update_builds_set_clause(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        pg.update("abc123", {"title": "New", "summary": "Sum"})

        execute_call = mock_cursor.execute.call_args
        query = execute_call[0][0]
        assert "title = %s" in query
        assert "summary = %s" in query
        assert "updated_at = NOW()" in query

    def test_update_rolls_back_on_error(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("DB error")
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        with pytest.raises(Exception, match="DB error"):
            pg.update("abc123", {"title": "X"})

        mock_conn.rollback.assert_called_once()

    def test_update_returns_connection_to_pool(self, pg):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.rowcount = 1
        pg.pool.getconn.return_value = mock_conn

        pg.update("abc123", {"title": "X"})

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGet:
    def test_get_returns_list_of_news(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 1, "unique_id": "abc123", "agency_id": 1, "title": "Test",
                "published_at": datetime(2024, 1, 1),
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        results = pg.get(filters={"unique_id": "abc123"})

        assert len(results) == 1
        assert isinstance(results[0], News)
        assert results[0].unique_id == "abc123"

    def test_get_with_no_filters_returns_all(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        results = pg.get()

        execute_call = mock_cursor.execute.call_args
        query = execute_call[0][0]
        assert "WHERE" not in query

    def test_get_applies_limit(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        pg.get(limit=10)

        execute_call = mock_cursor.execute.call_args
        query = execute_call[0][0]
        assert "LIMIT 10" in query

    def test_get_returns_connection_to_pool(self, pg):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.fetchall.return_value = []
        pg.pool.getconn.return_value = mock_conn

        pg.get()

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGetByUniqueId:
    def test_returns_news_when_found(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": 1, "unique_id": "abc123", "agency_id": 1, "title": "Test",
                "published_at": datetime(2024, 1, 1),
            }
        ]
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.get_by_unique_id("abc123")

        assert result is not None
        assert result.unique_id == "abc123"

    def test_returns_none_when_not_found(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.get_by_unique_id("nonexistent")

        assert result is None


class TestCount:
    def test_count_without_filters(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (250,)
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.count()

        assert result == 250
        execute_call = mock_cursor.execute.call_args
        query = execute_call[0][0]
        assert "WHERE" not in query

    def test_count_with_filters(self, pg):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (10,)
        mock_conn.cursor.return_value = mock_cursor
        pg.pool.getconn.return_value = mock_conn

        result = pg.count(filters={"agency_key": "mec"})

        assert result == 10
        execute_call = mock_cursor.execute.call_args
        query = execute_call[0][0]
        assert "WHERE" in query
        assert "agency_key = %s" in query

    def test_count_returns_connection_to_pool(self, pg):
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.fetchone.return_value = (0,)
        pg.pool.getconn.return_value = mock_conn

        pg.count()

        pg.pool.putconn.assert_called_once_with(mock_conn)
