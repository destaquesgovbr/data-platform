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
    update_schema,
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


class TestUpdateSchema:
    """Tests for update_schema() function."""

    def test_adds_missing_fields(self):
        """Adds fields that exist in schema but not in live collection."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            "fields": [
                {"name": "unique_id", "type": "string", "facet": True},
                {"name": "published_at", "type": "int64", "facet": False},
            ]
        }
        mock_collection.update.return_value = {}
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "unique_id", "type": "string", "facet": True},
                {"name": "published_at", "type": "int64", "facet": False},
                {"name": "content_hash", "type": "string", "facet": True, "optional": True},
            ],
        }

        result = update_schema(mock_client, schema=schema)

        assert "content_hash" in result["added"]
        assert "unique_id" in result["already_exists"]
        assert "published_at" in result["already_exists"]
        mock_collection.update.assert_called_once_with(
            {"fields": [{"name": "content_hash", "type": "string", "facet": True, "optional": True}]}
        )

    def test_no_changes_when_schema_matches(self):
        """Returns empty added list when schema is already up to date."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            "fields": [
                {"name": "unique_id", "type": "string", "facet": True},
                {"name": "title", "type": "string", "facet": False},
            ]
        }
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "unique_id", "type": "string", "facet": True},
                {"name": "title", "type": "string", "facet": False},
            ],
        }

        result = update_schema(mock_client, schema=schema)

        assert result["added"] == []
        assert len(result["already_exists"]) == 2
        mock_collection.update.assert_not_called()

    def test_dry_run_does_not_apply(self):
        """Dry run reports missing fields without applying."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"fields": []}
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "content_hash", "type": "string", "facet": True, "optional": True},
            ],
        }

        result = update_schema(mock_client, schema=schema, dry_run=True)

        assert "content_hash" in result["added"]
        mock_collection.update.assert_not_called()

    def test_raises_on_nonexistent_collection(self):
        """Raises ValueError if collection does not exist."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.side_effect = ObjectNotFound("Not found")
        mock_client.collections.__getitem__.return_value = mock_collection

        with pytest.raises(ValueError, match="não encontrada"):
            update_schema(mock_client)

    def test_handles_partial_failure(self):
        """Records errors for fields that fail to add."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"fields": []}
        mock_collection.update.side_effect = Exception("Bad field type")
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "bad_field", "type": "invalid", "facet": True},
            ],
        }

        result = update_schema(mock_client, schema=schema)

        assert result["added"] == []
        assert len(result["errors"]) == 1
        assert result["errors"][0]["field"] == "bad_field"


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
