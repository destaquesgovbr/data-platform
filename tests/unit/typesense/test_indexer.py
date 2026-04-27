"""
Unit tests for pure functions in Typesense indexer.

These functions have no side effects and require no mocking.
"""

import json
import struct
from unittest.mock import MagicMock, Mock

import numpy as np
import pandas as pd
import pytest

from data_platform.typesense.indexer import (
    MAX_TAG_LENGTH,
    clean_tags,
    parse_embedding,
    prepare_document,
)


class TestCleanTags:
    """Tests for clean_tags() function."""

    def test_clean_tags_from_list(self):
        """Clean tags from a regular list."""
        tags = ["python", "data", "  spaces  ", ""]
        result = clean_tags(tags)
        assert result == ["python", "data", "spaces"]

    def test_clean_tags_from_numpy_array(self):
        """Clean tags from numpy array (via tolist())."""
        tags = np.array(["python", "data", "ml"])
        result = clean_tags(tags)
        assert result == ["python", "data", "ml"]

    def test_clean_tags_filters_non_strings(self):
        """Filter out non-string types."""
        tags = ["python", 123, "data", None, "ml"]
        result = clean_tags(tags)
        assert result == ["python", "data", "ml"]

    def test_clean_tags_filters_empty_strings(self):
        """Filter out empty strings after strip."""
        tags = ["python", "", "   ", "data"]
        result = clean_tags(tags)
        assert result == ["python", "data"]

    def test_clean_tags_filters_long_strings(self):
        """Filter out tags longer than MAX_TAG_LENGTH (100 chars)."""
        long_tag = "a" * (MAX_TAG_LENGTH + 1)
        tags = ["python", long_tag, "data"]
        result = clean_tags(tags)
        assert result == ["python", "data"]

    def test_clean_tags_keeps_max_length_tag(self):
        """Keep tags exactly at MAX_TAG_LENGTH."""
        max_tag = "a" * MAX_TAG_LENGTH
        tags = ["python", max_tag]
        result = clean_tags(tags)
        assert result == ["python", max_tag]

    def test_clean_tags_none_input(self):
        """Handle None input."""
        result = clean_tags(None)
        assert result == []

    def test_clean_tags_number_input(self):
        """Handle number input."""
        result = clean_tags(123)
        assert result == []

    def test_clean_tags_dict_input(self):
        """Handle dict input."""
        result = clean_tags({"tag": "python"})
        assert result == []


class TestParseEmbedding:
    """Tests for parse_embedding() function."""

    def test_parse_embedding_none(self):
        """Handle None input."""
        result = parse_embedding(None)
        assert result is None

    def test_parse_embedding_list(self):
        """Pass through list directly."""
        embedding = [1.0, 2.0, 3.0]
        result = parse_embedding(embedding)
        assert result == [1.0, 2.0, 3.0]

    def test_parse_embedding_json_string_valid(self):
        """Parse valid JSON string."""
        embedding_str = "[1.0, 2.0, 3.0]"
        result = parse_embedding(embedding_str)
        assert result == [1.0, 2.0, 3.0]

    def test_parse_embedding_json_string_invalid(self):
        """Handle invalid JSON string."""
        embedding_str = "[1.0, 2.0, invalid]"
        result = parse_embedding(embedding_str)
        assert result is None

    def test_parse_embedding_bytes_pgvector(self):
        """Parse pgvector binary format (2 bytes dim + floats)."""
        # pgvector format: dimension (uint16 big-endian) + floats (big-endian)
        dim = 3
        floats = [1.0, 2.0, 3.0]
        data = struct.pack("!H", dim) + struct.pack(f"!{dim}f", *floats)

        result = parse_embedding(data)
        assert result == pytest.approx([1.0, 2.0, 3.0])

    def test_parse_embedding_memoryview(self):
        """Parse memoryview (convert to bytes first)."""
        dim = 2
        floats = [5.5, 6.6]
        data = struct.pack("!H", dim) + struct.pack(f"!{dim}f", *floats)
        mv = memoryview(data)

        result = parse_embedding(mv)
        assert result == pytest.approx([5.5, 6.6])

    def test_parse_embedding_bytes_invalid(self):
        """Handle invalid bytes (malformed pgvector)."""
        data = b"invalid"
        result = parse_embedding(data)
        assert result is None

    def test_parse_embedding_unknown_type(self):
        """Handle unknown type."""
        result = parse_embedding({"embedding": [1.0]})
        assert result is None


class TestPrepareDocument:
    """Tests for prepare_document() function."""

    def test_prepare_document_basic(self):
        """Prepare document with required fields."""
        row = pd.Series(
            {
                "unique_id": "abc123",
                "published_at_ts": 1704067200,
                "title": "Test News",
                "agency": "mec",
            }
        )

        doc = prepare_document(row)

        assert doc["id"] == "abc123"
        assert doc["unique_id"] == "abc123"
        assert doc["published_at"] == 1704067200
        assert doc["title"] == "Test News"
        assert doc["agency"] == "mec"

    def test_prepare_document_missing_published_at_ts(self):
        """Handle missing published_at_ts (default to 0)."""
        row = pd.Series({"unique_id": "abc123", "title": "Test"})

        doc = prepare_document(row)
        assert doc["published_at"] == 0

    def test_prepare_document_optional_fields(self):
        """Include optional fields when present."""
        row = pd.Series(
            {
                "unique_id": "abc123",
                "published_at_ts": 1704067200,
                "image": "https://example.com/image.jpg",
                "video_url": "https://example.com/video.mp4",
                "category": "Educação",
            }
        )

        doc = prepare_document(row)
        assert doc["image"] == "https://example.com/image.jpg"
        assert doc["video_url"] == "https://example.com/video.mp4"
        assert doc["category"] == "Educação"

    def test_prepare_document_feature_fields(self):
        """Include feature fields from news_features JOIN."""
        row = pd.Series(
            {
                "unique_id": "abc123",
                "published_at_ts": 1704067200,
                "sentiment_label": "positive",
                "sentiment_score": 0.85,
                "word_count": 500,
                "has_image": True,
                "has_video": False,
            }
        )

        doc = prepare_document(row)
        assert doc["sentiment_label"] == "positive"
        assert doc["sentiment_score"] == 0.85
        assert doc["word_count"] == 500
        assert doc["has_image"] is True
        assert doc["has_video"] is False

    def test_prepare_document_tags_cleaning(self):
        """Tags are cleaned via clean_tags()."""
        row = pd.Series(
            {
                "unique_id": "abc123",
                "published_at_ts": 1704067200,
                "tags": ["python", "  data  ", "", "ml"],
            }
        )

        doc = prepare_document(row)
        assert doc["tags"] == ["python", "data", "ml"]

    def test_prepare_document_embedding(self):
        """Embedding is parsed via parse_embedding()."""
        row = pd.Series(
            {
                "unique_id": "abc123",
                "published_at_ts": 1704067200,
                "content_embedding": [0.1, 0.2, 0.3],
            }
        )

        doc = prepare_document(row)
        assert doc["content_embedding"] == [0.1, 0.2, 0.3]


class TestIndexDocuments:
    """Tests for index_documents() function."""

    def _make_client(self, num_documents=0, import_results=None):
        """Build a MagicMock typesense client (supports collections[name] subscript)."""
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"num_documents": num_documents, "fields": []}
        if import_results is not None:
            mock_collection.documents.import_.return_value = import_results
        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        return mock_client, mock_collection

    def test_index_small_batch(self):
        """Index small batch of documents."""
        from data_platform.typesense.indexer import index_documents

        df = pd.DataFrame(
            {
                "unique_id": ["abc", "def"],
                "title": ["News 1", "News 2"],
                "published_at_ts": [1704067200, 1704153600],
            }
        )
        mock_client, _ = self._make_client(
            import_results=[{"success": True}, {"success": True}]
        )

        stats = index_documents(mock_client, df)

        assert stats["total_processed"] == 2
        assert stats["total_indexed"] == 2
        assert stats["errors"] == 0

    def test_index_full_mode_skips_nonempty_without_force(self):
        """Full mode without force skips non-empty collection."""
        from data_platform.typesense.indexer import index_documents

        df = pd.DataFrame({"unique_id": ["abc"], "published_at_ts": [1704067200]})
        mock_client, mock_collection = self._make_client(num_documents=1000)

        stats = index_documents(mock_client, df, mode="full", force=False)

        assert stats["skipped"] is True
        mock_collection.documents.import_.assert_not_called()

    def test_index_full_mode_proceeds_with_force(self):
        """Full mode with force proceeds even if collection non-empty."""
        from data_platform.typesense.indexer import index_documents

        df = pd.DataFrame({"unique_id": ["abc"], "published_at_ts": [1704067200]})
        mock_client, _ = self._make_client(
            num_documents=1000, import_results=[{"success": True}]
        )

        stats = index_documents(mock_client, df, mode="full", force=True)

        assert stats["skipped"] is False
        assert stats["total_indexed"] == 1

    def test_index_handles_partial_errors(self):
        """Index counts partial errors correctly."""
        from data_platform.typesense.indexer import index_documents

        df = pd.DataFrame(
            {
                "unique_id": ["abc", "def", "ghi"],
                "published_at_ts": [1704067200, 1704153600, 1704240000],
            }
        )
        mock_client, _ = self._make_client(
            import_results=[
                {"success": True},
                {"success": False, "error": "Validation error"},
                {"success": True},
            ]
        )

        stats = index_documents(mock_client, df)

        assert stats["total_processed"] == 3
        # Note: known bug - only increments if ZERO errors in batch
        assert stats["errors"] == 1

    def test_index_empty_dataframe(self):
        """Index empty DataFrame returns zero stats."""
        from data_platform.typesense.indexer import index_documents

        df = pd.DataFrame(columns=["unique_id", "published_at_ts"])
        mock_client, _ = self._make_client()

        stats = index_documents(mock_client, df)

        assert stats["total_processed"] == 0
        assert stats["total_indexed"] == 0
        assert stats["skipped"] is False
