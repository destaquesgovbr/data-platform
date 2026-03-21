"""Tests for Bronze Writer GraphQL integration."""

from unittest.mock import MagicMock, patch

import pytest

from data_platform.workers.bronze_writer.handler import (
    _fetch_full_article_via_graphql,
    handle_bronze_write,
)


@pytest.fixture
def mock_gql_client():
    return MagicMock()


@pytest.fixture
def sample_graphql_response():
    return {
        "newsById": {
            "uniqueId": "article-456",
            "title": "Bronze Test Article",
            "url": "https://example.gov.br/news/456",
            "imageUrl": "https://example.gov.br/img.jpg",
            "videoUrl": None,
            "content": "Full article content.",
            "summary": "Summary",
            "subtitle": None,
            "editorialLead": None,
            "category": "general",
            "tags": ["tag1"],
            "agencyKey": "example",
            "agencyName": "Example Agency",
            "publishedAt": "2025-06-15T10:00:00Z",
            "extractedAt": "2025-06-15T12:00:00Z",
            "themL1Code": "01",
            "themL1Label": "Theme L1",
            "themL2Code": None,
            "themL2Label": None,
            "themL3Code": None,
            "themL3Label": None,
            "mostSpecificThemeCode": "01",
            "mostSpecificThemeLabel": "Theme L1",
            "features": None,
        }
    }


class TestFetchFullArticleViaGraphql:
    def test_fetch_full_article_via_graphql(self, mock_gql_client, sample_graphql_response):
        mock_gql_client.query.return_value = sample_graphql_response

        result = _fetch_full_article_via_graphql("article-456", mock_gql_client)

        assert result is not None
        assert result["unique_id"] == "article-456"
        assert result["title"] == "Bronze Test Article"
        assert result["url"] == "https://example.gov.br/news/456"
        assert result["image_url"] == "https://example.gov.br/img.jpg"
        assert result["content"] == "Full article content."
        assert result["agency_key"] == "example"
        assert result["agency_name"] == "Example Agency"
        assert result["published_at"] == "2025-06-15T10:00:00Z"
        assert result["theme_l1_code"] == "01"
        assert result["most_specific_theme_code"] == "01"
        mock_gql_client.query.assert_called_once()

    def test_fetch_not_found(self, mock_gql_client):
        mock_gql_client.query.return_value = {"newsById": None}

        result = _fetch_full_article_via_graphql("nonexistent", mock_gql_client)

        assert result is None


class TestHandleUsesGraphql:
    @patch("data_platform.workers.bronze_writer.handler.write_to_gcs")
    @patch("data_platform.workers.bronze_writer.handler.build_gcs_path")
    @patch.dict("os.environ", {"GCS_BUCKET": "test-bucket"})
    def test_handle_uses_graphql_when_client_provided(
        self, mock_build_path, mock_write_gcs, mock_gql_client, sample_graphql_response
    ):
        mock_gql_client.query.return_value = sample_graphql_response
        mock_build_path.return_value = "bronze/news/2025/06/15/article-456.json"

        mock_pg = MagicMock()

        result = handle_bronze_write("article-456", mock_pg, gql_client=mock_gql_client)

        assert result["status"] == "written"
        assert result["unique_id"] == "article-456"
        assert result["gcs_path"] == "bronze/news/2025/06/15/article-456.json"
        # Should NOT have called PostgresManager methods
        mock_pg.get_connection.assert_not_called()
        # Should have called GraphQL client
        mock_gql_client.query.assert_called_once()
        # Should have written to GCS
        mock_write_gcs.assert_called_once()
