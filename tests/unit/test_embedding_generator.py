"""
Unit tests for EmbeddingGenerator.

Phase 4.7: Embeddings Semânticos (HTTP API version)
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import httpx
import numpy as np
import pytest

from data_platform.jobs.embeddings import EmbeddingGenerator


class TestEmbeddingGenerator:
    """Tests for EmbeddingGenerator class."""

    @pytest.fixture
    def mock_database_url(self) -> str:
        """Mock database URL."""
        return "postgresql://user:pass@localhost:5432/test"

    @pytest.fixture
    def mock_api_url(self) -> str:
        """Mock API URL."""
        return "https://embeddings-api.example.com"

    @pytest.fixture
    def mock_api_key(self) -> str:
        """Mock API key."""
        return "test-api-key-12345"

    @pytest.fixture
    def mock_identity_token(self) -> str:
        """Mock identity token."""
        return "test-identity-token-xyz"

    @pytest.fixture
    def generator(
        self,
        mock_database_url: str,
        mock_api_url: str,
        mock_api_key: str,
        mock_identity_token: str,
    ) -> EmbeddingGenerator:
        """Create EmbeddingGenerator instance with mocked credentials."""
        return EmbeddingGenerator(
            database_url=mock_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
            identity_token=mock_identity_token,
        )

    def test_init_with_all_params(
        self,
        mock_database_url: str,
        mock_api_url: str,
        mock_api_key: str,
        mock_identity_token: str,
    ) -> None:
        """Test initialization with all explicit parameters."""
        generator = EmbeddingGenerator(
            database_url=mock_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
            identity_token=mock_identity_token,
        )
        assert generator.database_url == mock_database_url
        assert generator.api_url == mock_api_url
        assert generator.api_key == mock_api_key
        assert generator._identity_token == mock_identity_token

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization from environment variables."""
        test_db_url = "postgresql://env:pass@localhost:5432/test"
        test_api_url = "https://api.example.com"
        test_api_key = "env-api-key"
        test_token = "env-token"

        monkeypatch.setenv("DATABASE_URL", test_db_url)
        monkeypatch.setenv("EMBEDDINGS_API_URL", test_api_url)
        monkeypatch.setenv("EMBEDDINGS_API_KEY", test_api_key)
        monkeypatch.setenv("EMBEDDINGS_IDENTITY_TOKEN", test_token)

        generator = EmbeddingGenerator()
        assert generator.database_url == test_db_url
        assert generator.api_url == test_api_url
        assert generator.api_key == test_api_key
        assert generator._identity_token == test_token

    def test_init_missing_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization fails without DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("EMBEDDINGS_API_URL", raising=False)
        monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)

        with pytest.raises(ValueError, match="DATABASE_URL environment variable is required"):
            EmbeddingGenerator()

    def test_init_missing_api_url(
        self, monkeypatch: pytest.MonkeyPatch, mock_database_url: str
    ) -> None:
        """Test initialization fails without EMBEDDINGS_API_URL."""
        monkeypatch.delenv("EMBEDDINGS_API_URL", raising=False)
        monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)

        with pytest.raises(ValueError, match="EMBEDDINGS_API_URL environment variable is required"):
            EmbeddingGenerator(database_url=mock_database_url)

    def test_init_missing_api_key(
        self, monkeypatch: pytest.MonkeyPatch, mock_database_url: str, mock_api_url: str
    ) -> None:
        """Test initialization fails without EMBEDDINGS_API_KEY."""
        monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)

        with pytest.raises(ValueError, match="EMBEDDINGS_API_KEY environment variable is required"):
            EmbeddingGenerator(database_url=mock_database_url, api_url=mock_api_url)

    def test_prepare_text_with_summary(self, generator: EmbeddingGenerator) -> None:
        """Test text preparation with title and summary."""
        title = "Governo anuncia nova política"
        summary = "Resumo gerado pela IA com detalhes da política."
        content = "Conteúdo completo muito longo da notícia..."

        text = generator._prepare_text_for_embedding(title, summary, content)

        assert title in text
        assert summary in text
        # Content should NOT be included when summary is present
        assert content not in text
        # Should be title + " " + summary
        assert text == f"{title} {summary}"

    def test_prepare_text_fallback_to_content(self, generator: EmbeddingGenerator) -> None:
        """Test text preparation falls back to content when summary is missing."""
        title = "Título da notícia"
        summary = None
        content = "Este é o conteúdo da notícia. " * 100  # Long content

        text = generator._prepare_text_for_embedding(title, summary, content)

        assert title in text
        # Should include first 500 chars of content
        assert len(text) <= len(title) + 501  # title + space + 500 chars
        assert content[:100] in text  # At least beginning of content

    def test_prepare_text_empty_summary_fallback(self, generator: EmbeddingGenerator) -> None:
        """Test text preparation falls back when summary is empty string."""
        title = "Título"
        summary = "   "  # Empty/whitespace only
        content = "Conteúdo válido"

        text = generator._prepare_text_for_embedding(title, summary, content)

        # Should use content since summary is empty
        assert title in text
        assert content in text

    def test_prepare_text_truncates_long_content(self, generator: EmbeddingGenerator) -> None:
        """Test that very long text is truncated."""
        title = "Título"
        summary = None
        # Create very long content (> MAX_TEXT_LENGTH * 4)
        content = "x" * (generator.MAX_TEXT_LENGTH * 5)

        text = generator._prepare_text_for_embedding(title, summary, content)

        # Should be truncated to MAX_TEXT_LENGTH * 4
        expected_max = len(title) + 1 + generator.MAX_TEXT_LENGTH * 4
        assert len(text) <= expected_max

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_batch_api_call(
        self, mock_client_class: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test batch embedding generation via API call."""
        texts = [
            "Governo anuncia nova política educacional",
            "Ministério da Saúde divulga dados",
            "Presidente participa de evento",
        ]

        # Mock API response
        fake_embeddings = np.random.rand(3, 768).astype(np.float32).tolist()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": fake_embeddings,
            "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            "dimension": 768,
            "count": 3,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        embeddings = generator._generate_embeddings_batch(texts)

        # Check shape
        assert embeddings.shape == (3, 768)

        # Verify API was called correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/generate" in call_args[0][0]
        assert call_args[1]["json"]["texts"] == texts
        assert "Authorization" in call_args[1]["headers"]
        assert "X-API-Key" in call_args[1]["headers"]
        assert call_args[1]["headers"]["X-API-Key"] == generator.api_key

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_batch_invalid_response(
        self, mock_client_class: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test error handling for invalid API response."""
        texts = ["Test text"]

        # Mock invalid API response (missing embeddings key)
        mock_response = MagicMock()
        mock_response.json.return_value = {"error": "something went wrong"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        with pytest.raises(ValueError, match="missing 'embeddings' key"):
            generator._generate_embeddings_batch(texts)

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_batch_wrong_dimension(
        self, mock_client_class: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test error handling for wrong embedding dimension."""
        texts = ["Test text"]

        # Mock API response with wrong dimension
        fake_embeddings = np.random.rand(1, 512).astype(np.float32).tolist()  # Wrong dim
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": fake_embeddings,
            "dimension": 512,
            "count": 1,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        with pytest.raises(ValueError, match="Unexpected embedding dimension"):
            generator._generate_embeddings_batch(texts)

    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    def test_fetch_news_without_embeddings(
        self, mock_connect: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test fetching news records without embeddings."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock query results
        mock_cursor.fetchall.return_value = [
            (1, "Título 1", "Resumo 1", "Conteúdo 1"),
            (2, "Título 2", "Resumo 2", "Conteúdo 2"),
        ]

        results = generator._fetch_news_without_embeddings(
            start_date="2025-01-01", end_date="2025-01-02", limit=10
        )

        # Verify results
        assert len(results) == 2
        assert results[0][0] == 1  # ID
        assert results[0][1] == "Título 1"  # Title
        assert results[0][2] == "Resumo 1"  # Summary

        # Verify query was executed with correct params
        mock_cursor.execute.assert_called_once()
        query, params = mock_cursor.execute.call_args[0]
        assert "content_embedding IS NULL" in query
        assert "LIMIT" in query
        assert params == ["2025-01-01", "2025-01-02", 10]

    @patch("data_platform.jobs.embeddings.embedding_generator.execute_batch")
    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    def test_update_embeddings_batch(
        self, mock_connect: Mock, mock_execute_batch: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test updating news records with embeddings."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        news_ids = [1, 2, 3]
        embeddings = np.random.rand(3, 768).astype(np.float32)

        updated = generator._update_embeddings_batch(news_ids, embeddings)

        # Verify result
        assert updated == 3

        # Verify execute_batch was called
        mock_execute_batch.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("data_platform.jobs.embeddings.embedding_generator.execute_batch")
    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_end_to_end(
        self, mock_client_class: Mock, mock_connect: Mock, mock_execute_batch: Mock,
        generator: EmbeddingGenerator
    ) -> None:
        """Test full generate_embeddings workflow (mocked DB and API)."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock fetch results (2 news without embeddings)
        mock_cursor.fetchall.return_value = [
            (1, "Título 1", "Resumo 1", "Conteúdo 1"),
            (2, "Título 2", None, "Conteúdo 2"),  # No summary
        ]

        # Mock API response
        fake_embeddings = np.random.rand(2, 768).astype(np.float32).tolist()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": fake_embeddings,
            "dimension": 768,
            "count": 2,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Run generate_embeddings
        stats = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-01", batch_size=100
        )

        # Verify stats
        assert stats["processed"] == 2
        assert stats["successful"] == 2
        assert stats["failed"] == 0

        # Verify API was called
        mock_client.post.assert_called_once()

        # Verify execute_batch was called
        mock_execute_batch.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    def test_generate_embeddings_no_records(
        self, mock_connect: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test generate_embeddings when no records found."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # No records
        mock_cursor.fetchall.return_value = []

        stats = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-01"
        )

        # Should return zero stats
        assert stats["processed"] == 0
        assert stats["successful"] == 0
        assert stats["failed"] == 0

    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_api_error_handling(
        self, mock_client_class: Mock, mock_connect: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test that API errors are handled gracefully."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock fetch results
        mock_cursor.fetchall.return_value = [
            (1, "Título 1", "Resumo 1", "Conteúdo 1"),
        ]

        # Mock API error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__ = MagicMock(return_value=None)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Run generate_embeddings - should not raise, but count as failed
        stats = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-01"
        )

        # Verify error was handled
        assert stats["processed"] == 1
        assert stats["successful"] == 0
        assert stats["failed"] == 1
