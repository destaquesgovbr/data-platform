"""
Tests for Typesense Sync Worker — GraphQL integration.

Validates:
- camelCase → snake_case mapping from GraphQL response
- Fallback to PostgreSQL when no GraphQL client is provided
- Correct routing when GraphQL client IS provided
"""

from unittest.mock import MagicMock, patch

import pytest

from data_platform.clients.graphql_client import GraphQLClient
from data_platform.workers.typesense_sync.handler import (
    _map_graphql_row,
    fetch_news_for_typesense_via_graphql,
    upsert_to_typesense,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_GRAPHQL_RESPONSE = {
    "uniqueId": "abc-123",
    "title": "Test Article",
    "url": "https://example.gov.br/article",
    "imageUrl": "https://example.gov.br/img.jpg",
    "videoUrl": None,
    "content": "Full article text here.",
    "summary": "A short summary.",
    "subtitle": "Subtitle text",
    "editorialLead": "Lead paragraph",
    "category": "Saúde",
    "tags": ["saúde", "covid"],
    "agencyKey": "ministerio-saude",
    "agencyName": "Ministério da Saúde",
    "publishedAt": "2025-06-15T10:30:00+00:00",
    "extractedAt": "2025-06-15T12:00:00+00:00",
    "themL1Code": "SAUDE",
    "themL1Label": "Saúde",
    "themL2Code": "SAUDE_PUBLICA",
    "themL2Label": "Saúde Pública",
    "themL3Code": None,
    "themL3Label": None,
    "mostSpecificThemeCode": "SAUDE_PUBLICA",
    "mostSpecificThemeLabel": "Saúde Pública",
    "contentEmbedding": [0.1, 0.2, 0.3],
    "sentimentLabel": "positive",
    "sentimentScore": 0.85,
    "trendingScore": 12.5,
    "wordCount": 350,
    "hasImage": True,
    "hasVideo": False,
    "imageBroken": False,
    "readabilityFlesch": 45.2,
}


# ---------------------------------------------------------------------------
# Tests: mapping
# ---------------------------------------------------------------------------


class TestMapGraphqlRow:
    def test_basic_field_mapping(self):
        mapped = _map_graphql_row(SAMPLE_GRAPHQL_RESPONSE)
        assert mapped["unique_id"] == "abc-123"
        assert mapped["title"] == "Test Article"
        assert mapped["agency"] == "ministerio-saude"
        assert mapped["content_embedding"] == [0.1, 0.2, 0.3]
        assert mapped["sentiment_label"] == "positive"
        assert mapped["word_count"] == 350

    def test_published_at_converted_to_epoch(self):
        mapped = _map_graphql_row(SAMPLE_GRAPHQL_RESPONSE)
        assert "published_at" not in mapped, "raw ISO string should be removed"
        assert isinstance(mapped["published_at_ts"], int)
        assert mapped["published_at_ts"] > 0
        assert mapped["published_year"] == 2025
        assert mapped["published_month"] == 6

    def test_extracted_at_converted_to_epoch(self):
        mapped = _map_graphql_row(SAMPLE_GRAPHQL_RESPONSE)
        assert "extracted_at" not in mapped
        assert isinstance(mapped["extracted_at_ts"], int)
        assert mapped["extracted_at_ts"] > 0

    def test_none_values_omitted(self):
        mapped = _map_graphql_row(SAMPLE_GRAPHQL_RESPONSE)
        # videoUrl and themL3Code are None in the fixture
        assert "video_url" not in mapped
        assert "theme_1_level_3_code" not in mapped

    def test_theme_mapping(self):
        mapped = _map_graphql_row(SAMPLE_GRAPHQL_RESPONSE)
        assert mapped["theme_1_level_1_code"] == "SAUDE"
        assert mapped["theme_1_level_2_label"] == "Saúde Pública"
        assert mapped["most_specific_theme_code"] == "SAUDE_PUBLICA"


# ---------------------------------------------------------------------------
# Tests: fetch via GraphQL
# ---------------------------------------------------------------------------


class TestFetchViaGraphql:
    def test_returns_mapped_dict(self):
        """GraphQL fetch returns a properly mapped dict when article exists."""
        mock_client = MagicMock(spec=GraphQLClient)
        mock_client.query.return_value = {
            "newsForTypesense": SAMPLE_GRAPHQL_RESPONSE,
        }

        result = fetch_news_for_typesense_via_graphql(mock_client, "abc-123")

        assert result is not None
        assert result["unique_id"] == "abc-123"
        assert result["title"] == "Test Article"
        assert isinstance(result["published_at_ts"], int)
        mock_client.query.assert_called_once()

    def test_not_found_returns_none(self):
        """GraphQL fetch returns None when article is not found."""
        mock_client = MagicMock(spec=GraphQLClient)
        mock_client.query.return_value = {"newsForTypesense": None}

        result = fetch_news_for_typesense_via_graphql(mock_client, "nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: upsert routing (GraphQL vs PG)
# ---------------------------------------------------------------------------


class TestUpsertRouting:
    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.prepare_document")
    @patch(
        "data_platform.workers.typesense_sync.handler.fetch_news_for_typesense_via_graphql"
    )
    def test_uses_graphql_when_client_provided(
        self, mock_gql_fetch, mock_prepare, mock_create_coll, mock_get_client
    ):
        """When gql_client is provided, GraphQL path is used."""
        mock_gql_fetch.return_value = {
            "unique_id": "abc-123",
            "published_at_ts": 1718444400,
            "title": "Test",
        }
        mock_prepare.return_value = {"id": "abc-123", "title": "Test"}
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        gql = MagicMock(spec=GraphQLClient)
        result = upsert_to_typesense("abc-123", gql_client=gql)

        assert result is True
        mock_gql_fetch.assert_called_once_with(gql, "abc-123")

    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.prepare_document")
    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_falls_back_to_pg_when_no_client(
        self, mock_pg_fetch, mock_prepare, mock_create_coll, mock_get_client
    ):
        """When gql_client is None, PostgreSQL path is used."""
        mock_pg_fetch.return_value = {
            "unique_id": "abc-123",
            "published_at_ts": 1718444400,
            "title": "Test",
        }
        mock_prepare.return_value = {"id": "abc-123", "title": "Test"}
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        pg = MagicMock()
        result = upsert_to_typesense("abc-123", pg=pg, gql_client=None)

        assert result is True
        mock_pg_fetch.assert_called_once_with(pg, "abc-123")
