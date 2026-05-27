"""Tests for batch_upsert_trending_via_graphql."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_platform.jobs.bigquery.trending import (
    batch_upsert_trending_via_graphql,
)


class TestUpsertTrendingViaGraphql:
    """Test that trending scores are sent via BATCH_UPSERT_FEATURES_MUTATION."""

    def test_upsert_trending_via_graphql(self):
        """Should call mutate with trending_score features."""
        mock_client = MagicMock()
        mock_client.mutate.return_value = {
            "batchUpsertFeatures": {"processed": 2, "failed": 0}
        }

        scores_df = pd.DataFrame([
            {"unique_id": "aaa", "trending_score": 2.5},
            {"unique_id": "bbb", "trending_score": 1.1},
        ])

        count = batch_upsert_trending_via_graphql(mock_client, scores_df)

        assert count == 2
        assert mock_client.mutate.call_count == 1

        sent_vars = mock_client.mutate.call_args[0][1]
        items = sent_vars["items"]
        assert len(items) == 2
        assert items[0] == {
            "uniqueId": "aaa",
            "features": {"trending_score": 2.5},
        }
        assert items[1] == {
            "uniqueId": "bbb",
            "features": {"trending_score": 1.1},
        }

    def test_upsert_trending_empty_df(self):
        """Empty DataFrame should return 0 without calling mutate."""
        mock_client = MagicMock()
        scores_df = pd.DataFrame(columns=["unique_id", "trending_score"])

        count = batch_upsert_trending_via_graphql(mock_client, scores_df)

        assert count == 0
        mock_client.mutate.assert_not_called()
