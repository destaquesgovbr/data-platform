"""Tests for Feature Worker GraphQL integration."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from data_platform.workers.feature_worker.handler import (
    _fetch_article_via_graphql,
    _upsert_features_via_graphql,
    handle_feature_computation,
)


@pytest.fixture
def mock_gql_client():
    return MagicMock()


@pytest.fixture
def sample_graphql_response():
    return {
        "newsById": {
            "uniqueId": "article-123",
            "title": "Test Article",
            "url": "https://example.gov.br/news/123",
            "imageUrl": "https://example.gov.br/img.jpg",
            "videoUrl": None,
            "content": "Full article content here.",
            "summary": "Summary text",
            "subtitle": None,
            "editorialLead": None,
            "category": "general",
            "tags": [],
            "agencyKey": "example",
            "agencyName": "Example Agency",
            "publishedAt": "2025-06-15T10:00:00Z",
            "extractedAt": "2025-06-15T12:00:00Z",
            "themeL1Code": "01",
            "themeL1Label": "Theme L1",
            "themeL2Code": None,
            "themeL2Label": None,
            "themeL3Code": None,
            "themeL3Label": None,
            "mostSpecificThemeCode": "01",
            "mostSpecificThemeLabel": "Theme L1",
            "features": None,
        }
    }


class TestFetchArticleViaGraphql:
    def test_fetch_article_via_graphql(self, mock_gql_client, sample_graphql_response):
        mock_gql_client.query.return_value = sample_graphql_response

        result = _fetch_article_via_graphql("article-123", mock_gql_client)

        assert result is not None
        assert result["unique_id"] == "article-123"
        assert result["content"] == "Full article content here."
        assert result["image_url"] == "https://example.gov.br/img.jpg"
        assert result["video_url"] is None
        # DateTime do GraphQL chega como str ISO; o handler entrega datetime UTC
        assert result["published_at"] == datetime(2025, 6, 15, 10, 0, tzinfo=UTC)
        mock_gql_client.query.assert_called_once()

    def test_fetch_article_not_found(self, mock_gql_client):
        mock_gql_client.query.return_value = {"newsById": None}

        result = _fetch_article_via_graphql("nonexistent", mock_gql_client)

        assert result is None


class TestUpsertFeaturesViaGraphql:
    def test_upsert_features_via_graphql(self, mock_gql_client):
        features = {"word_count": 150, "has_image": True}

        _upsert_features_via_graphql("article-123", features, mock_gql_client)

        mock_gql_client.mutate.assert_called_once()
        call_args = mock_gql_client.mutate.call_args
        variables = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("variables")
        assert variables["uniqueId"] == "article-123"
        # O escalar JSON recebe o objeto. Uma string (json.dumps) seria gravada
        # como jsonb string e o merge `features || $2::jsonb` viraria array.
        assert variables["features"] == {"word_count": 150, "has_image": True}


class TestHandleUsesGraphql:
    @patch("data_platform.workers.feature_worker.handler.compute_all")
    def test_handle_uses_graphql_when_client_provided(
        self, mock_compute_all, mock_gql_client, sample_graphql_response
    ):
        mock_gql_client.query.return_value = sample_graphql_response
        mock_compute_all.return_value = {"word_count": 42, "has_image": True}

        mock_pg = MagicMock()

        result = handle_feature_computation("article-123", mock_pg, gql_client=mock_gql_client)

        assert result["status"] == "computed"
        assert result["unique_id"] == "article-123"
        assert "word_count" in result["features"]
        # Should NOT have called PostgresManager methods
        mock_pg.upsert_features.assert_not_called()
        # Should have called GraphQL client
        mock_gql_client.query.assert_called_once()
        mock_gql_client.mutate.assert_called_once()

    def test_handle_graphql_sem_mock_calcula_publicacao(
        self, mock_gql_client, sample_graphql_response
    ):
        """compute_all real: publishedAt str não pode quebrar publication_hour."""
        mock_gql_client.query.return_value = sample_graphql_response

        result = handle_feature_computation("article-123", MagicMock(), gql_client=mock_gql_client)

        assert result["status"] == "computed"
        features = mock_gql_client.mutate.call_args[0][1]["features"]
        assert isinstance(features, dict)
        assert features["publication_hour"] == 10
        assert features["publication_dow"] == 6  # domingo
