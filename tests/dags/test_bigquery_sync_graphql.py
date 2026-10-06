"""Tests for fetch_news_for_bigquery_via_graphql (query newsBatchForBigquery)."""

from unittest.mock import MagicMock

import pandas as pd

from data_platform.jobs.bigquery.sync_to_bigquery import (
    fetch_news_for_bigquery_via_graphql,
)


def _make_article(unique_id: str) -> dict:
    """Helper: um item de newsBatchForBigquery conforme BigQueryRecordType do SDL.

    charCount, paragraphCount, publicationHour e publicationDow não existem no
    schema; chegam dentro do blob `features`.
    """
    return {
        "uniqueId": unique_id,
        "title": f"Title {unique_id}",
        "url": f"https://example.gov.br/{unique_id}",
        "agencyKey": "mci",
        "agencyName": "MCI",
        "publishedAt": "2025-06-01T10:00:00Z",
        "extractedAt": "2025-06-01T11:00:00Z",
        "themeL1Code": "T01",
        "themeL1Label": "Economia",
        "themeL2Code": "T01.01",
        "themeL2Label": "PIB",
        "mostSpecificThemeCode": "T01.01",
        "mostSpecificThemeLabel": "PIB",
        "wordCount": 300,
        "hasImage": True,
        "hasVideo": False,
        "sentimentLabel": "positive",
        "sentimentScore": 0.8,
        "readabilityFlesch": 55.0,
        "features": {
            "word_count": 300,
            "char_count": 1500,
            "paragraph_count": 5,
            "publication_hour": 10,
            "publication_dow": 6,
        },
    }


class TestFetchViaGraphqlPaginates:
    """Test that fetch_news_for_bigquery_via_graphql handles pagination."""

    def test_fetch_via_graphql_paginates(self):
        """Two pages of results should be concatenated into one DataFrame."""
        page1 = [_make_article(f"id-{i}") for i in range(3)]
        page2 = [_make_article(f"id-{i}") for i in range(3, 5)]

        mock_client = MagicMock()
        mock_client.query.side_effect = [
            {"newsBatchForBigquery": page1},
            {"newsBatchForBigquery": page2},
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
        """camelCase do GraphQL vira as colunas do SYNC_QUERY (mesmo schema de load)."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"newsBatchForBigquery": [_make_article("abc")]}

        df = fetch_news_for_bigquery_via_graphql(mock_client, "2025-06-01", "2025-06-02")

        expected_cols = {
            "unique_id",
            "title",
            "url",
            "content_hash",
            "agency_key",
            "agency_name",
            "published_at",
            "extracted_at",
            "synced_at",
            "theme_l1_code",
            "theme_l1_label",
            "theme_l2_code",
            "theme_l2_label",
            "most_specific_theme_code",
            "most_specific_theme_label",
            "word_count",
            "char_count",
            "paragraph_count",
            "has_image",
            "has_video",
            "sentiment_label",
            "sentiment_score",
            "readability_flesch",
            "publication_hour",
            "publication_dow",
        }
        assert set(df.columns) == expected_cols

    def test_features_fields_mapped(self):
        mock_client = MagicMock()
        mock_client.query.return_value = {"newsBatchForBigquery": [_make_article("abc")]}

        row = fetch_news_for_bigquery_via_graphql(mock_client, "2025-06-01", "2025-06-02").iloc[0]

        assert row["theme_l1_code"] == "T01"
        assert row["char_count"] == 1500
        assert row["paragraph_count"] == 5
        assert row["publication_hour"] == 10
        assert row["publication_dow"] == 6


class TestFetchViaGraphqlEmptyRange:
    """Test behaviour when GraphQL returns no data."""

    def test_fetch_via_graphql_empty_range(self):
        """Empty result from GraphQL should return empty DataFrame."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"newsBatchForBigquery": []}

        df = fetch_news_for_bigquery_via_graphql(mock_client, "2099-01-01", "2099-01-02")

        assert isinstance(df, pd.DataFrame)
        assert df.empty
        assert mock_client.query.call_count == 1
