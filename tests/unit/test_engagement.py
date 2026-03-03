"""Unit tests for engagement metrics aggregation."""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from data_platform.jobs.bigquery.engagement import (
    ENGAGEMENT_QUERY,
    batch_upsert_engagement,
)


class TestEngagementQuery:
    def test_query_reads_from_umami_pageviews(self):
        assert "umami_pageviews" in ENGAGEMENT_QUERY

    def test_query_extracts_unique_id_from_url_path(self):
        assert "REGEXP_EXTRACT(url_path" in ENGAGEMENT_QUERY
        assert "/artigos/" in ENGAGEMENT_QUERY

    def test_query_counts_views(self):
        assert "COUNT(*) AS view_count" in ENGAGEMENT_QUERY

    def test_query_counts_unique_sessions(self):
        assert "COUNT(DISTINCT session_id) AS unique_sessions" in ENGAGEMENT_QUERY

    def test_query_uses_project_id_placeholder(self):
        assert "{project_id}" in ENGAGEMENT_QUERY

    def test_query_filters_artigos_path(self):
        assert "url_path LIKE '/artigos/%'" in ENGAGEMENT_QUERY

    def test_query_filters_null_unique_ids(self):
        assert "HAVING unique_id IS NOT NULL" in ENGAGEMENT_QUERY


class TestBatchUpsertEngagement:

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_all_rows(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        df = pd.DataFrame({
            "unique_id": ["art-1", "art-2"],
            "view_count": [100, 50],
            "unique_sessions": [80, 40],
        })
        count = batch_upsert_engagement("postgresql://test", df)
        assert count == 2
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_correct_features(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        df = pd.DataFrame({
            "unique_id": ["art-1"],
            "view_count": [42],
            "unique_sessions": [30],
        })
        batch_upsert_engagement("postgresql://test", df)

        mock_pg.upsert_features.assert_called_once_with(
            "art-1", {"view_count": 42, "unique_sessions": 30}
        )

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_empty_dataframe(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        df = pd.DataFrame(columns=["unique_id", "view_count", "unique_sessions"])
        count = batch_upsert_engagement("postgresql://test", df)
        assert count == 0
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_closes_pg_on_error(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.side_effect = Exception("DB error")

        df = pd.DataFrame({
            "unique_id": ["art-1"],
            "view_count": [10],
            "unique_sessions": [5],
        })
        with pytest.raises(Exception, match="DB error"):
            batch_upsert_engagement("postgresql://test", df)

        mock_pg.close_all.assert_called_once()
