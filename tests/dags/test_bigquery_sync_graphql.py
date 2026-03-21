"""Tests for fetch_news_for_bigquery_via_graphql."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_platform.jobs.bigquery.sync_to_bigquery import (
    fetch_news_for_bigquery_via_graphql,
)


def _make_article(unique_id: str) -> dict:
    """Helper: create a single GraphQL response article."""
    return {
        "uniqueId": unique_id,
        "title": f"Title {unique_id}",
        "url": f"https://example.gov.br/{unique_id}",
        "agencyKey": "mci",
        "agencyName": "MCI",
        "publishedAt": "2025-06-01T10:00:00Z",
        "themL1Code": "T01",
        "themL1Label": "Economia",
        "themL2Code": "T01.01",
        "themL2Label": "PIB",
        "themL3Code": None,
        "themL3Label": None,
        "mostSpecificThemeCode": "T01.01",
        "mostSpecificThemeLabel": "PIB",
        "wordCount": 300,
        "charCount": 1500,
        "paragraphCount": 5,
        "hasImage": True,
        "hasVideo": False,
        "sentimentLabel": "positive",
        "sentimentScore": 0.8,
        "readabilityFlesch": 55.0,
        "publicationHour": 10,
        "publicationDow": 2,
    }


class TestFetchViaGraphqlPaginates:
    """Test that fetch_news_for_bigquery_via_graphql handles pagination."""

    def test_fetch_via_graphql_paginates(self):
        """Two pages of results should be concatenated into one DataFrame."""
        page1 = [_make_article(f"id-{i}") for i in range(3)]
        page2 = [_make_article(f"id-{i}") for i in range(3, 5)]

        mock_client = MagicMock()
        mock_client.query.side_effect = [
            {"newsBatchForBigQuery": page1},
            {"newsBatchForBigQuery": page2},
        ]

        df = fetch_news_for_bigquery_via_graphql(
            mock_client, "2025-06-01", "2025-06-02", batch_size=3
        )

        assert len(df) == 5
        assert list(df["unique_id"]) == [f"id-{i}" for i in range(5)]

        # Should have made 2 queries
        assert mock_client.query.call_count == 2

        # First call: no cursor
        first_vars = mock_client.query.call_args_list[0][0][1]
        assert "cursor" not in first_vars

        # Second call: cursor from last item of page1
        second_vars = mock_client.query.call_args_list[1][0][1]
        assert second_vars["cursor"] == "id-2"

    def test_columns_are_snake_case(self):
        """Verify camelCase GraphQL fields are converted to snake_case."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "newsBatchForBigQuery": [_make_article("abc")]
        }

        df = fetch_news_for_bigquery_via_graphql(
            mock_client, "2025-06-01", "2025-06-02"
        )

        expected_cols = {
            "unique_id", "title", "url", "agency_key", "agency_name",
            "published_at", "theme_l1_code", "theme_l1_label",
            "theme_l2_code", "theme_l2_label",
            "most_specific_theme_code", "most_specific_theme_label",
            "word_count", "char_count", "paragraph_count",
            "has_image", "has_video", "sentiment_label", "sentiment_score",
            "readability_flesch", "publication_hour", "publication_dow",
        }
        assert set(df.columns) == expected_cols


class TestFetchViaGraphqlEmptyRange:
    """Test behaviour when GraphQL returns no data."""

    def test_fetch_via_graphql_empty_range(self):
        """Empty result from GraphQL should return empty DataFrame."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"newsBatchForBigQuery": []}

        df = fetch_news_for_bigquery_via_graphql(
            mock_client, "2099-01-01", "2099-01-02"
        )

        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert mock_client.query.call_count == 1
