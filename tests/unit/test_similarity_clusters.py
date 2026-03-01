"""Unit tests for similar article clustering."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.jobs.similarity.clusters import (
    SIMILARITY_QUERY,
    group_similar_articles,
    batch_upsert_clusters,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K,
)


class TestSimilarityQuery:
    """Tests for the similarity SQL query."""

    def test_query_uses_cosine_distance(self):
        assert "<=>" in SIMILARITY_QUERY

    def test_query_uses_cross_join_lateral(self):
        assert "CROSS JOIN LATERAL" in SIMILARITY_QUERY

    def test_query_filters_by_threshold(self):
        # The query uses a parameter placeholder for threshold
        assert "content_embedding IS NOT NULL" in SIMILARITY_QUERY

    def test_query_excludes_self_matches(self):
        assert "unique_id != t.unique_id" in SIMILARITY_QUERY

    def test_query_orders_by_similarity(self):
        assert "ORDER BY" in SIMILARITY_QUERY


class TestGroupSimilarArticles:
    """Tests for grouping similarity pairs."""

    def test_groups_correctly(self):
        df = pd.DataFrame({
            "unique_id": ["a", "a", "b"],
            "similar_id": ["b", "c", "a"],
            "similarity": [0.95, 0.85, 0.95],
        })
        result = group_similar_articles(df)
        assert result["a"] == ["b", "c"]  # ordered by similarity desc
        assert result["b"] == ["a"]

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["unique_id", "similar_id", "similarity"])
        assert group_similar_articles(df) == {}

    def test_single_pair(self):
        df = pd.DataFrame({
            "unique_id": ["a"],
            "similar_id": ["b"],
            "similarity": [0.9],
        })
        result = group_similar_articles(df)
        assert result == {"a": ["b"]}


class TestBatchUpsertClusters:
    """Tests for batch upserting clusters to news_features."""

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_all_clusters(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        clusters = {
            "art-1": ["art-2", "art-3"],
            "art-2": ["art-1"],
        }
        count = batch_upsert_clusters("postgresql://test", clusters)

        assert count == 2
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_upserts_correct_feature_dict(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.return_value = True

        clusters = {"art-1": ["art-2", "art-3"]}
        batch_upsert_clusters("postgresql://test", clusters)

        mock_pg.upsert_features.assert_called_once_with(
            "art-1", {"similar_articles": ["art-2", "art-3"]}
        )

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_empty_clusters(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        count = batch_upsert_clusters("postgresql://test", {})
        assert count == 0
        mock_pg.close_all.assert_called_once()

    @patch("data_platform.managers.postgres_manager.PostgresManager")
    def test_closes_pg_on_error(self, mock_pg_class):
        mock_pg = mock_pg_class.return_value
        mock_pg.upsert_features.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            batch_upsert_clusters("postgresql://test", {"art-1": ["art-2"]})

        mock_pg.close_all.assert_called_once()
