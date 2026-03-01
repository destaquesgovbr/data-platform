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


class TestBatchUpsertTrending:
    """Tests for batch_upsert_trending function."""

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_all_rows(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        df = pd.DataFrame({
            "unique_id": ["art-1", "art-2", "art-3"],
            "trending_score": [2.5, 1.8, 0.5],
        })

        count = batch_upsert_trending("postgresql://test", df)

        assert count == 3
        assert mock_pg.upsert_features.call_count == 3
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_handles_empty_dataframe(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value

        df = pd.DataFrame(columns=["unique_id", "trending_score"])
        count = batch_upsert_trending("postgresql://test", df)

        assert count == 0
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_correct_feature_dict(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        df = pd.DataFrame({
            "unique_id": ["art-1"],
            "trending_score": [3.14],
        })

        batch_upsert_trending("postgresql://test", df)

        mock_pg.upsert_features.assert_called_once_with(
            "art-1", {"trending_score": 3.14}
        )

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_closes_pg_on_error(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.side_effect = Exception("DB error")

        df = pd.DataFrame({
            "unique_id": ["art-1"],
            "trending_score": [1.0],
        })

        with pytest.raises(Exception, match="DB error"):
            batch_upsert_trending("postgresql://test", df)

        mock_pg.close_all.assert_called_once()
