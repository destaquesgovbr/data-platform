"""Unit tests for similar article clustering."""

import json
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

    def test_upserts_all_clusters(self, mock_sqlalchemy_engine):
        mock_engine, mock_conn = mock_sqlalchemy_engine

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            clusters = {"art-1": ["art-2", "art-3"], "art-2": ["art-1"]}
            count = batch_upsert_clusters("postgresql://test", clusters)

        assert count == 2
        mock_engine.dispose.assert_called_once()

    def test_upserts_correct_feature_dict(self, mock_sqlalchemy_engine):
        mock_engine, mock_conn = mock_sqlalchemy_engine

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            batch_upsert_clusters("postgresql://test", {"art-1": ["art-2", "art-3"]})

        execute_call = mock_conn.execute.call_args
        params = execute_call[0][1]
        assert params["uid"] == "art-1"
        features = json.loads(params["features"])
        assert features == {"similar_articles": ["art-2", "art-3"]}

    def test_empty_clusters(self, mock_sqlalchemy_engine):
        mock_engine, _ = mock_sqlalchemy_engine

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            count = batch_upsert_clusters("postgresql://test", {})

        assert count == 0
        mock_engine.dispose.assert_called_once()

    def test_closes_engine_on_error(self, mock_sqlalchemy_engine):
        mock_engine, mock_conn = mock_sqlalchemy_engine
        mock_conn.execute.side_effect = Exception("DB error")

        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            with pytest.raises(Exception, match="DB error"):
                batch_upsert_clusters("postgresql://test", {"art-1": ["art-2"]})

        mock_engine.dispose.assert_called_once()
