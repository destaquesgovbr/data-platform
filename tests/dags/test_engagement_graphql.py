"""Tests for batch_upsert_engagement_via_graphql."""

from unittest.mock import MagicMock, call

import pandas as pd
import pytest

from data_platform.jobs.bigquery.engagement import (
    batch_upsert_engagement_via_graphql,
)


class TestUpsertEngagementViaGraphql:
    """Test that engagement metrics are sent via BATCH_UPSERT_FEATURES_MUTATION."""

    def test_upsert_engagement_via_graphql(self):
        """Should call mutate with correct items structure."""
        mock_client = MagicMock()
        mock_client.mutate.return_value = {
            "batchUpsertFeatures": {"processed": 3, "failed": 0}
        }

        metrics_df = pd.DataFrame([
            {"unique_id": "aaa", "view_count": 100, "unique_sessions": 50},
            {"unique_id": "bbb", "view_count": 200, "unique_sessions": 80},
            {"unique_id": "ccc", "view_count": 10, "unique_sessions": 5},
        ])

        count = batch_upsert_engagement_via_graphql(mock_client, metrics_df)

        assert count == 3
        assert mock_client.mutate.call_count == 1

        # Verify the items payload
        sent_vars = mock_client.mutate.call_args[0][1]
        items = sent_vars["items"]
        assert len(items) == 3
        assert items[0] == {
            "uniqueId": "aaa",
            "features": {"view_count": 100, "unique_sessions": 50},
        }
        assert items[2] == {
            "uniqueId": "ccc",
            "features": {"view_count": 10, "unique_sessions": 5},
        }

    def test_upsert_engagement_empty_df(self):
        """Empty DataFrame should return 0 without calling mutate."""
        mock_client = MagicMock()
        metrics_df = pd.DataFrame(columns=["unique_id", "view_count", "unique_sessions"])

        count = batch_upsert_engagement_via_graphql(mock_client, metrics_df)

        assert count == 0
        mock_client.mutate.assert_not_called()

    def test_upsert_engagement_batches_large_payload(self):
        """More than 500 items should be sent in multiple batches."""
        mock_client = MagicMock()
        mock_client.mutate.return_value = {
            "batchUpsertFeatures": {"processed": 500, "failed": 0}
        }

        rows = [
            {"unique_id": f"id-{i}", "view_count": i, "unique_sessions": i // 2}
            for i in range(600)
        ]
        metrics_df = pd.DataFrame(rows)

        count = batch_upsert_engagement_via_graphql(mock_client, metrics_df)

        # Two batches: 500 + 100
        assert mock_client.mutate.call_count == 2
        assert count == 1000  # 500 + 500 (mock returns 500 each time)
