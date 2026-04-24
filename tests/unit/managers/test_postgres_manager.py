"""
Unit tests for PostgresManager.

Tests are organized by functional area:
- Core: init, cache, context manager, connection string
- Models: Pydantic model validation
- SQLAlchemy: engine creation and disposal
- Features: upsert_features, get_features, get_features_batch
- Typesense: query building, count/get/iter for typesense sync
- CRUD: update, get, get_by_unique_id, count
"""

import os
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest
from pydantic import ValidationError

from data_platform.managers import PostgresManager
from data_platform.models import Agency, News, NewsInsert, Theme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn_with_results(fetchone_return=None, fetchall_return=None):
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


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


class TestPostgresManagerCore:
    @patch("data_platform.managers.postgres_manager.pool")
    @patch("data_platform.managers.postgres_manager.subprocess")
    def test_init(self, mock_subprocess: Mock, mock_pool: Mock) -> None:
        mock_subprocess.run.return_value = Mock(
            returncode=0, stdout="postgresql://user:pass@host:5432/db\n"
        )

        manager = PostgresManager(min_connections=2, max_connections=5)

        assert manager.pool is not None
        assert manager._cache_loaded is False
        assert len(manager._agencies_by_key) == 0
        assert len(manager._themes_by_code) == 0

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_agency_by_key(self, mock_pool: Mock) -> None:
        manager = PostgresManager(connection_string="postgresql://test")

        agency = Agency(id=1, key="mec", name="Ministério da Educação")
        manager._agencies_by_key["mec"] = agency
        manager._cache_loaded = True

        result = manager.get_agency_by_key("mec")

        assert result is not None
        assert result.key == "mec"
        assert result.name == "Ministério da Educação"

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_agency_by_key_not_found(self, mock_pool: Mock) -> None:
        manager = PostgresManager(connection_string="postgresql://test")
        manager._cache_loaded = True

        result = manager.get_agency_by_key("nonexistent")

        assert result is None

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_theme_by_code(self, mock_pool: Mock) -> None:
        manager = PostgresManager(connection_string="postgresql://test")

        theme = Theme(id=1, code="01", label="Economia", level=1)
        manager._themes_by_code["01"] = theme
        manager._cache_loaded = True

        result = manager.get_theme_by_code("01")

        assert result is not None
        assert result.code == "01"
        assert result.label == "Economia"
        assert result.level == 1

    @patch("data_platform.managers.postgres_manager.pool")
    def test_insert_empty_list_raises_error(self, mock_pool: Mock) -> None:
        manager = PostgresManager(connection_string="postgresql://test")

        with pytest.raises(ValueError, match="News list cannot be empty"):
            manager.insert([])

    @patch("data_platform.managers.postgres_manager.pool")
    def test_update_empty_dict_raises_error(self, mock_pool: Mock) -> None:
        manager = PostgresManager(connection_string="postgresql://test")

        with pytest.raises(ValueError, match="Updates dictionary cannot be empty"):
            manager.update("unique123", {})

    @patch("data_platform.managers.postgres_manager.pool")
    def test_context_manager(self, mock_pool: Mock) -> None:
        mock_pool_instance = MagicMock()
        mock_pool.SimpleConnectionPool.return_value = mock_pool_instance

        with PostgresManager(connection_string="postgresql://test") as manager:
            assert manager is not None

        mock_pool_instance.closeall.assert_called_once()


class TestPostgresManagerConnectionString:
    @patch("data_platform.managers.postgres_manager.subprocess.run")
    @patch("data_platform.managers.postgres_manager.pool")
    def test_connection_string_with_cloud_sql_proxy(self, mock_pool: Mock, mock_run: Mock) -> None:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="postgresql://user:pass@10.5.0.3:5432/db\n",
            check=True,
        )

        env_without_db = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        with patch("data_platform.managers.postgres_manager.subprocess.run") as mock_subprocess, \
             patch.dict(os.environ, env_without_db, clear=True):

            def run_side_effect(*args: Any, **kwargs: Any) -> Mock:
                if args[0][0] == "pgrep":
                    return Mock(returncode=0)
                elif args[0][0] == "gcloud":
                    return Mock(returncode=0, stdout="postgresql://user:pass@10.5.0.3:5432/db\n")
                return Mock(returncode=1)

            mock_subprocess.side_effect = run_side_effect

            manager = PostgresManager()
            conn_str = manager.connection_string

            assert "127.0.0.1" in conn_str
            assert "5432" in conn_str


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    def test_news_model(self) -> None:
        news = News(
            id=1,
            unique_id="test123",
            agency_id=1,
            title="Test News",
            published_at=datetime(2024, 1, 1),
        )

        assert news.id == 1
        assert news.unique_id == "test123"
        assert news.title == "Test News"

    def test_news_insert_model(self) -> None:
        news = NewsInsert(
            unique_id="test123",
            agency_id=1,
            title="Test News",
            published_at=datetime(2024, 1, 1),
        )

        assert news.unique_id == "test123"
        assert news.title == "Test News"

    def test_agency_model(self) -> None:
        agency = Agency(id=1, key="mec", name="Ministério da Educação", type="Ministério")

        assert agency.id == 1
        assert agency.key == "mec"
        assert agency.name == "Ministério da Educação"

    def test_theme_model(self) -> None:
        theme = Theme(id=1, code="01", label="Economia", level=1)

        assert theme.id == 1
        assert theme.code == "01"
        assert theme.level == 1

    def test_theme_level_validation(self) -> None:
        Theme(code="01", label="Test", level=1)
        Theme(code="02", label="Test", level=2)
        Theme(code="03", label="Test", level=3)

        with pytest.raises(ValidationError):
            Theme(code="04", label="Test", level=4)


# ---------------------------------------------------------------------------
# SQLAlchemy Engine
# ---------------------------------------------------------------------------


class TestSQLAlchemyEngine:
    @patch("data_platform.managers.postgres_manager.pool")
    @patch("data_platform.managers.postgres_manager.create_engine")
    def test_engine_created_with_nullpool(self, mock_create_engine: Mock, mock_pool: Mock) -> None:
        from sqlalchemy.pool import NullPool

        PostgresManager(connection_string="postgresql://test")

        mock_create_engine.assert_called_once_with("postgresql://test", poolclass=NullPool)

    @patch("data_platform.managers.postgres_manager.pool")
    @patch("data_platform.managers.postgres_manager.create_engine")
    def test_engine_disposed_on_close_all(self, mock_create_engine: Mock, mock_pool: Mock) -> None:
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_pool_instance = MagicMock()
        mock_pool.SimpleConnectionPool.return_value = mock_pool_instance

        manager = PostgresManager(connection_string="postgresql://test")
        manager.close_all()

        mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# Features (upsert_features, get_features, get_features_batch)
# ---------------------------------------------------------------------------


class TestUpsertFeatures:
    def test_upsert_features_insert(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        result = pg.upsert_features("abc123", {"word_count": 150})

        assert result is True
        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO news_features" in sql
        assert "ON CONFLICT" in sql
        assert "features || EXCLUDED.features" in sql
        mock_conn.commit.assert_called_once()

    def test_upsert_features_merge(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        result = pg.upsert_features("abc123", {"has_image": True, "sentiment": {"score": 0.8}})

        assert result is True
        params = cursor.execute.call_args[0][1]
        assert params[0] == "abc123"

    def test_upsert_features_empty_dict_returns_false(self, pg, mock_conn):
        result = pg.upsert_features("abc123", {})

        assert result is False
        mock_conn.cursor.assert_not_called()

    def test_upsert_features_rollback_on_error(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            pg.upsert_features("abc123", {"word_count": 100})

        mock_conn.rollback.assert_called_once()

    def test_upsert_features_connection_returned(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.rowcount = 1

        pg.upsert_features("abc123", {"word_count": 100})

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGetFeatures:
    def test_get_features_existing(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {"features": {"word_count": 150, "has_image": True}}

        result = pg.get_features("abc123")

        assert result == {"word_count": 150, "has_image": True}
        cursor.execute.assert_called_once()
        assert "abc123" in cursor.execute.call_args[0][1]

    def test_get_features_nonexistent(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = pg.get_features("nonexistent")

        assert result is None

    def test_get_features_connection_returned(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        pg.get_features("abc123")

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGetFeaturesBatch:
    def test_get_features_batch(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {"unique_id": "abc123", "features": {"word_count": 150}},
            {"unique_id": "def456", "features": {"word_count": 200}},
        ]

        result = pg.get_features_batch(["abc123", "def456"])

        assert result == {
            "abc123": {"word_count": 150},
            "def456": {"word_count": 200},
        }
        sql = cursor.execute.call_args[0][0]
        assert "ANY(%s)" in sql

    def test_get_features_batch_partial(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {"unique_id": "abc123", "features": {"word_count": 150}},
        ]

        result = pg.get_features_batch(["abc123", "missing"])

        assert "abc123" in result
        assert "missing" not in result

    def test_get_features_batch_empty_list(self, pg, mock_conn):
        result = pg.get_features_batch([])

        assert result == {}
        mock_conn.cursor.assert_not_called()

    def test_get_features_batch_connection_returned(self, pg, mock_conn):
        cursor = MagicMock()
        mock_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = []

        pg.get_features_batch(["abc123"])

        pg.pool.putconn.assert_called_once_with(mock_conn)


# ---------------------------------------------------------------------------
# Typesense query building
# ---------------------------------------------------------------------------


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
        mock_conn, mock_cursor = _make_conn_with_results(fetchone_return=(42,))
        pg.pool.getconn.return_value = mock_conn

        result = pg.count_news_for_typesense("2024-01-01")

        assert result == 42

    def test_end_date_defaults_to_start_date(self, pg):
        mock_conn, mock_cursor = _make_conn_with_results(fetchone_return=(0,))
        pg.pool.getconn.return_value = mock_conn

        pg.count_news_for_typesense("2024-01-15")

        execute_call = mock_cursor.execute.call_args
        params = execute_call[0][1]
        assert params[0] == "2024-01-15"
        assert params[1] == "2024-01-15"

    def test_returns_zero_for_empty_range(self, pg):
        mock_conn, mock_cursor = _make_conn_with_results(fetchone_return=(0,))
        pg.pool.getconn.return_value = mock_conn

        result = pg.count_news_for_typesense("2024-01-01", "2024-01-01")

        assert result == 0

    def test_connection_returned_to_pool(self, pg):
        mock_conn, _ = _make_conn_with_results(fetchone_return=(5,))
        pg.pool.getconn.return_value = mock_conn

        pg.count_news_for_typesense("2024-01-01")

        pg.pool.putconn.assert_called_once_with(mock_conn)


class TestGetNewsForTypesense:
    def test_returns_dataframe(self, pg):
        expected_df = pd.DataFrame({"unique_id": ["abc123"], "title": ["Test"]})
        pg._engine.connect = MagicMock()
        pg._engine.__class__ = MagicMock

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


# ---------------------------------------------------------------------------
# CRUD: update, get, get_by_unique_id, count
# ---------------------------------------------------------------------------


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
