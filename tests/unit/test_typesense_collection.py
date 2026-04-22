"""
Unit tests for Typesense collection management.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from typesense.exceptions import ObjectNotFound

from data_platform.typesense.collection import (
    COLLECTION_NAME,
    COLLECTION_SCHEMA,
    create_collection,
    delete_collection,
    list_collections,
)


class TestCollectionSchema:
    """Tests for COLLECTION_SCHEMA constant."""

    def test_schema_has_name(self):
        """Schema includes collection name."""
        assert COLLECTION_SCHEMA["name"] == "news"

    def test_schema_has_required_fields(self):
        """Schema includes all required fields."""
        field_names = [f["name"] for f in COLLECTION_SCHEMA["fields"]]

        required = ["unique_id", "published_at", "title", "agency"]
        for field in required:
            assert field in field_names

    def test_unique_id_is_facetable(self):
        """unique_id field is configured as facet."""
        unique_id_field = next(
            f for f in COLLECTION_SCHEMA["fields"] if f["name"] == "unique_id"
        )
        assert unique_id_field["facet"] is True

    def test_published_at_is_int64(self):
        """published_at is int64 (Unix timestamp)."""
        pub_field = next(
            f for f in COLLECTION_SCHEMA["fields"] if f["name"] == "published_at"
        )
        assert pub_field["type"] == "int64"


class TestCreateCollection:
    """Tests for create_collection() function."""

    def test_create_new_collection(self):
        """Create new collection when it doesn't exist."""
        mock_client = MagicMock()
        mock_collection_proxy = MagicMock()
        mock_collection_proxy.retrieve.side_effect = ObjectNotFound("Not found")
        mock_client.collections.__getitem__.return_value = mock_collection_proxy
        mock_client.collections.create.return_value = {"name": "news"}

        result = create_collection(mock_client)

        assert result is True
        mock_client.collections.create.assert_called_once_with(COLLECTION_SCHEMA)

    def test_create_idempotent_when_exists(self):
        """Create is idempotent - returns True if collection exists."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"name": "news"}
        mock_client.collections.__getitem__.return_value = mock_collection

        result = create_collection(mock_client)

        assert result is True
        mock_client.collections.create.assert_not_called()

    def test_create_propagates_error(self):
        """Create propagates exceptions (does not return False)."""
        mock_client = MagicMock()
        mock_collection_proxy = MagicMock()
        mock_collection_proxy.retrieve.side_effect = ObjectNotFound("Not found")
        mock_client.collections.__getitem__.return_value = mock_collection_proxy
        mock_client.collections.create.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            create_collection(mock_client)


class TestDeleteCollection:
    """Tests for delete_collection() function."""

    def test_delete_existing_collection(self):
        """Delete existing collection."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        # First retrieve returns info; second (post-delete verification) raises ObjectNotFound
        mock_collection.retrieve.side_effect = [{"num_documents": 100}, ObjectNotFound("gone")]
        mock_client.collections.__getitem__.return_value = mock_collection

        with patch("builtins.input", return_value="DELETE"), \
             patch("data_platform.typesense.collection.time.sleep"):
            result = delete_collection(mock_client)

        assert result is True
        mock_collection.delete.assert_called()

    def test_delete_nonexistent_returns_false(self):
        """Delete non-existent collection returns False."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.side_effect = ObjectNotFound("Not found")
        mock_client.collections.__getitem__.return_value = mock_collection

        result = delete_collection(mock_client)

        assert result is False

    def test_delete_with_confirm_skips_prompt(self):
        """Delete with confirm=True skips interactive prompt."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.side_effect = [{"num_documents": 100}, ObjectNotFound("gone")]
        mock_client.collections.__getitem__.return_value = mock_collection

        with patch("data_platform.typesense.collection.time.sleep"):
            result = delete_collection(mock_client, confirm=True)

        assert result is True


class TestListCollections:
    """Tests for list_collections() function."""

    def test_list_returns_collection_dicts(self):
        """List returns full dict info for all collections."""
        mock_client = Mock()
        mock_client.collections.retrieve.return_value = [
            {"name": "news", "num_documents": 100},
            {"name": "archive", "num_documents": 50},
        ]

        result = list_collections(mock_client)

        assert result == [
            {"name": "news", "num_documents": 100},
            {"name": "archive", "num_documents": 50},
        ]

    def test_list_empty_returns_empty_list(self):
        """List with no collections returns empty list."""
        mock_client = Mock()
        mock_client.collections.retrieve.return_value = []

        result = list_collections(mock_client)

        assert result == []

    def test_list_handles_api_error(self):
        """List returns empty list on API error."""
        mock_client = Mock()
        mock_client.collections.retrieve.side_effect = Exception("API error")

        result = list_collections(mock_client)

        assert result == []
