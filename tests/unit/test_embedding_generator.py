"""
Unit tests for EmbeddingGenerator.

Phase 4.7: Embeddings Semânticos
"""

import os
from datetime import datetime
from typing import List
from unittest.mock import MagicMock, Mock, patch

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
    def generator(self, mock_database_url: str) -> EmbeddingGenerator:
        """Create EmbeddingGenerator instance with mocked DB."""
        return EmbeddingGenerator(database_url=mock_database_url)

    def test_init_with_database_url(self, mock_database_url: str) -> None:
        """Test initialization with explicit database URL."""
        generator = EmbeddingGenerator(database_url=mock_database_url)
        assert generator.database_url == mock_database_url

    def test_init_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization from DATABASE_URL env var."""
        test_url = "postgresql://env:pass@localhost:5432/test"
        monkeypatch.setenv("DATABASE_URL", test_url)

        generator = EmbeddingGenerator()
        assert generator.database_url == test_url

    def test_init_missing_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization fails without DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(ValueError, match="DATABASE_URL environment variable is required"):
            EmbeddingGenerator()

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

    @patch("data_platform.jobs.embeddings.embedding_generator.SentenceTransformer")
    def test_model_lazy_loading(
        self, mock_sentence_transformer: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test that model is loaded lazily on first access."""
        # Model should not be loaded yet
        assert generator._model is None

        # Access model property
        _ = generator.model

        # Model should be loaded
        mock_sentence_transformer.assert_called_once_with(
            generator.MODEL_NAME, device=generator._device
        )
        assert generator._model is not None

    @patch("data_platform.jobs.embeddings.embedding_generator.SentenceTransformer")
    def test_model_loaded_only_once(
        self, mock_sentence_transformer: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test that model is loaded only once (cached)."""
        # Access model twice
        _ = generator.model
        _ = generator.model

        # Should only be called once
        mock_sentence_transformer.assert_called_once()

    def test_generate_embeddings_batch(self, generator: EmbeddingGenerator) -> None:
        """Test batch embedding generation (mocked model)."""
        texts = [
            "Governo anuncia nova política educacional",
            "Ministério da Saúde divulga dados",
            "Presidente participa de evento",
        ]

        # Mock the model
        mock_model = MagicMock()
        # Return fake embeddings (3 texts × 768 dimensions)
        fake_embeddings = np.random.rand(3, 768).astype(np.float32)
        mock_model.encode.return_value = fake_embeddings
        generator._model = mock_model

        embeddings = generator._generate_embeddings_batch(texts)

        # Check shape
        assert embeddings.shape == (3, 768)
        # Check model was called correctly
        mock_model.encode.assert_called_once()
        call_args = mock_model.encode.call_args
        assert call_args[0][0] == texts
        assert call_args[1]["batch_size"] == generator.DEFAULT_BATCH_SIZE
        assert call_args[1]["normalize_embeddings"] is True

    def test_embedding_similarity(self, generator: EmbeddingGenerator) -> None:
        """Test that similar texts produce similar embeddings (requires real model)."""
        # Skip if model download would fail (e.g., in CI without network)
        pytest.skip("Requires downloading real model (~420 MB)")

        # This test would require the real model
        # Kept as documentation of expected behavior
        texts = [
            "Governo anuncia nova política de educação",
            "Ministério da Educação divulga nova política",  # Similar
            "Previsão do tempo para amanhã",  # Different
        ]

        embeddings = generator._generate_embeddings_batch(texts)

        # Compute cosine similarities
        from numpy.linalg import norm

        def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
            return np.dot(a, b) / (norm(a) * norm(b))

        sim_0_1 = cosine_similarity(embeddings[0], embeddings[1])
        sim_0_2 = cosine_similarity(embeddings[0], embeddings[2])

        # Similar texts should have higher similarity
        assert sim_0_1 > sim_0_2
        assert sim_0_1 > 0.7  # High similarity for similar content
        assert sim_0_2 < 0.5  # Low similarity for different content

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
        assert "published_at >= '2025-01-01'" in query
        assert "LIMIT" in query
        assert params == ["2025-01-01", "2025-01-02", 10]

    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    def test_update_embeddings_batch(
        self, mock_connect: Mock, generator: EmbeddingGenerator
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
        # (Can't easily verify exact calls with execute_batch, but check commit was called)
        mock_conn.commit.assert_called_once()

    @patch("data_platform.jobs.embeddings.embedding_generator.psycopg2.connect")
    @patch.object(EmbeddingGenerator, "model", new_callable=lambda: MagicMock())
    def test_generate_embeddings_end_to_end(
        self, mock_model: Mock, mock_connect: Mock, generator: EmbeddingGenerator
    ) -> None:
        """Test full generate_embeddings workflow (mocked DB and model)."""
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

        # Mock model encode
        fake_embeddings = np.random.rand(2, 768).astype(np.float32)
        mock_model.encode.return_value = fake_embeddings

        # Run generate_embeddings
        stats = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-01", batch_size=100
        )

        # Verify stats
        assert stats["processed"] == 2
        assert stats["successful"] == 2
        assert stats["failed"] == 0

        # Verify model was called
        mock_model.encode.assert_called_once()

        # Verify commit was called
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
