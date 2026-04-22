"""Unit tests for trending score computation."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.jobs.bigquery.trending import TRENDING_QUERY, batch_upsert_trending


class TestTrendingQuery:
    """Tests for the trending SQL query."""

    def test_query_uses_window_functions(self):
        assert "PARTITION BY theme_l1_code" in TRENDING_QUERY

    def test_query_calculates_24h_and_7d(self):
        assert "86400" in TRENDING_QUERY  # 24h in seconds
        assert "604800" in TRENDING_QUERY  # 7d in seconds

    def test_query_has_trending_score(self):
        assert "trending_score" in TRENDING_QUERY

    def test_query_orders_by_score(self):
        assert "ORDER BY trending_score DESC" in TRENDING_QUERY

    def test_query_uses_project_id_placeholder(self):
        assert "{project_id}" in TRENDING_QUERY


def _make_engine_mock():
    """Build a mock SQLAlchemy engine that supports `with engine.begin() as conn`."""
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine, mock_conn


class TestBatchUpsertTrending:
    """Tests for batch_upsert_trending function."""

    def test_upserts_all_rows(self):
        mock_engine, mock_conn = _make_engine_mock()

        df = pd.DataFrame({
            "unique_id": ["art-1", "art-2", "art-3"],
            "trending_score": [2.5, 1.8, 0.5],
        })

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            count = batch_upsert_trending("postgresql://test", df)

        assert count == 3
        assert mock_conn.execute.call_count == 3
        mock_engine.dispose.assert_called_once()

    def test_handles_empty_dataframe(self):
        mock_engine, mock_conn = _make_engine_mock()

        df = pd.DataFrame(columns=["unique_id", "trending_score"])

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            count = batch_upsert_trending("postgresql://test", df)

        assert count == 0
        mock_engine.dispose.assert_called_once()

    def test_upserts_correct_feature_dict(self):
        mock_engine, mock_conn = _make_engine_mock()

        df = pd.DataFrame({
            "unique_id": ["art-1"],
            "trending_score": [3.14],
        })

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            batch_upsert_trending("postgresql://test", df)

        import json
        execute_call = mock_conn.execute.call_args
        params = execute_call[0][1]
        assert params["uid"] == "art-1"
        features = json.loads(params["features"])
        assert features == {"trending_score": pytest.approx(3.14)}

    def test_closes_engine_on_error(self):
        mock_engine, mock_conn = _make_engine_mock()
        mock_conn.execute.side_effect = Exception("DB error")

        df = pd.DataFrame({"unique_id": ["art-1"], "trending_score": [1.0]})

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            with pytest.raises(Exception, match="DB error"):
                batch_upsert_trending("postgresql://test", df)

        mock_engine.dispose.assert_called_once()
