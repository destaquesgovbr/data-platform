"""Tests for GraphQL-based cluster computation functions."""

from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from data_platform.jobs.similarity.clusters import (
    batch_upsert_clusters_via_graphql,
    fetch_similar_articles_via_graphql,
)


class TestFetchSimilarArticlesViaGraphQL:
    """Tests for fetch_similar_articles_via_graphql."""

    def test_returns_dataframe_with_correct_columns(self):
        gql_client = MagicMock()
        gql_client.query.return_value = {
            "similarArticles": [
                {"uniqueId": "b-1", "similarity": 0.95},
                {"uniqueId": "b-2", "similarity": 0.88},
            ]
        }

        df = fetch_similar_articles_via_graphql(gql_client, ["a-1"])

        assert list(df.columns) == ["unique_id", "similar_id", "similarity"]
        assert len(df) == 2
        assert df.iloc[0]["unique_id"] == "a-1"
        assert df.iloc[0]["similar_id"] == "b-1"
        assert df.iloc[0]["similarity"] == 0.95

    def test_handles_multiple_unique_ids(self):
        gql_client = MagicMock()
        gql_client.query.side_effect = [
            {"similarArticles": [{"uniqueId": "b-1", "similarity": 0.9}]},
            {"similarArticles": [{"uniqueId": "c-1", "similarity": 0.85}]},
        ]

        df = fetch_similar_articles_via_graphql(gql_client, ["a-1", "a-2"])

        assert len(df) == 2
        assert gql_client.query.call_count == 2
        assert df.iloc[0]["unique_id"] == "a-1"
        assert df.iloc[1]["unique_id"] == "a-2"

    def test_returns_empty_dataframe_when_no_results(self):
        gql_client = MagicMock()
        gql_client.query.return_value = {"similarArticles": []}

        df = fetch_similar_articles_via_graphql(gql_client, ["a-1"])

        assert df.empty
        assert list(df.columns) == ["unique_id", "similar_id", "similarity"]

    def test_returns_empty_dataframe_for_empty_ids(self):
        gql_client = MagicMock()

        df = fetch_similar_articles_via_graphql(gql_client, [])

        assert df.empty
        gql_client.query.assert_not_called()

    def test_passes_threshold_and_limit_to_query(self):
        gql_client = MagicMock()
        gql_client.query.return_value = {"similarArticles": []}

        fetch_similar_articles_via_graphql(
            gql_client, ["a-1"], threshold=0.9, limit=3
        )

        gql_client.query.assert_called_once()
        _, kwargs = gql_client.query.call_args
        # Check variables passed
        call_args = gql_client.query.call_args
        variables = call_args[0][1]  # second positional arg
        assert variables["threshold"] == 0.9
        assert variables["limit"] == 3
        assert variables["uniqueId"] == "a-1"


class TestBatchUpsertClustersViaGraphQL:
    """Tests for batch_upsert_clusters_via_graphql."""

    def test_upserts_clusters_and_returns_count(self):
        gql_client = MagicMock()
        gql_client.mutate.return_value = {
            "batchUpsertFeatures": {"processed": 2, "failed": 0}
        }

        clusters = {
            "a-1": ["b-1", "b-2"],
            "a-2": ["c-1"],
        }
        count = batch_upsert_clusters_via_graphql(gql_client, clusters)

        assert count == 2
        gql_client.mutate.assert_called_once()
        call_args = gql_client.mutate.call_args
        variables = call_args[0][1]
        items = variables["items"]
        assert len(items) == 2
        assert items[0]["uniqueId"] == "a-1"
        assert items[0]["features"] == {"similar_articles": ["b-1", "b-2"]}
        assert items[1]["uniqueId"] == "a-2"
        assert items[1]["features"] == {"similar_articles": ["c-1"]}

    def test_returns_zero_for_empty_clusters(self):
        gql_client = MagicMock()

        count = batch_upsert_clusters_via_graphql(gql_client, {})

        assert count == 0
        gql_client.mutate.assert_not_called()

    def test_handles_partial_failures(self):
        gql_client = MagicMock()
        gql_client.mutate.return_value = {
            "batchUpsertFeatures": {"processed": 1, "failed": 1}
        }

        clusters = {"a-1": ["b-1"], "a-2": ["c-1"]}
        count = batch_upsert_clusters_via_graphql(gql_client, clusters)

        assert count == 1
