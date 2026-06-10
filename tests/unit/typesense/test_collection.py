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

    def test_schema_has_entity_fields(self):
        """Schema includes combined + per-type entity fields as facetable string[]."""
        fields = {f["name"]: f for f in COLLECTION_SCHEMA["fields"]}
        for name in (
            "entities",
            "entity_org",
            "entity_per",
            "entity_loc",
            "entity_misc",
            "entity_event",
            "entity_policy",
            "entity_canonical",
        ):
            assert name in fields, f"missing entity field {name}"
            assert fields[name]["type"] == "string[]"
            assert fields[name]["facet"] is True
            assert fields[name]["optional"] is True

    def test_schema_declares_entity_misc(self):
        """entity_misc must be declared (indexer routes to it; was previously missing)."""
        field_names = [f["name"] for f in COLLECTION_SCHEMA["fields"]]
        assert "entity_misc" in field_names

    def test_schema_has_entity_canonical(self):
        """entity_canonical (deduped canonical_id list) is a facetable optional string[]."""
        fields = {f["name"]: f for f in COLLECTION_SCHEMA["fields"]}
        assert "entity_canonical" in fields
        ec = fields["entity_canonical"]
        assert ec["type"] == "string[]"
        assert ec["facet"] is True
        assert ec["optional"] is True

    def test_update_schema_patches_new_entity_fields_onto_existing(self):
        """update_schema() additively PATCHes the new entity fields onto a live collection."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        # Live collection has the old entity set but lacks the 3 new fields.
        mock_collection.retrieve.return_value = {
            "fields": [
                {"name": "unique_id", "type": "string", "facet": True},
                {"name": "entities", "type": "string[]", "facet": True},
                {"name": "entity_org", "type": "string[]", "facet": True},
                {"name": "entity_per", "type": "string[]", "facet": True},
                {"name": "entity_loc", "type": "string[]", "facet": True},
                {"name": "entity_misc", "type": "string[]", "facet": True},
            ]
        }
        mock_collection.update.return_value = {}
        mock_client.collections.__getitem__.return_value = mock_collection

        result = update_schema(mock_client)

        assert "entity_event" in result["added"]
        assert "entity_policy" in result["added"]
        assert "entity_canonical" in result["added"]
        # Pre-existing fields are not re-added.
        assert "entity_misc" in result["already_exists"]
        assert "entity_org" in result["already_exists"]

    def test_schema_has_view_count_sortable(self):
        """view_count is an optional, sortable int32."""
        fields = {f["name"]: f for f in COLLECTION_SCHEMA["fields"]}
        assert "view_count" in fields
        vc = fields["view_count"]
        assert vc["type"] == "int32"
        assert vc["optional"] is True
        assert vc["sort"] is True
        assert vc["facet"] is False


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

    @patch("data_platform.typesense.collection.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        """Retries on transient failure and succeeds on subsequent attempt."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"fields": []}
        mock_collection.update.side_effect = [Exception("Timeout"), {}]
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "content_hash", "type": "string", "facet": True, "optional": True},
            ],
        }

        result = update_schema(mock_client, schema=schema)

        assert "content_hash" in result["added"]
        assert result["errors"] == []
        assert mock_collection.update.call_count == 2
        mock_sleep.assert_called_once()

    @patch("data_platform.typesense.collection.time.sleep")
    def test_records_errors_after_max_retries(self, mock_sleep):
        """Records errors for all fields after exhausting retries."""
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
        assert mock_collection.update.call_count == 3

    def test_batch_adds_multiple_fields_atomically(self):
        """Adds multiple fields in a single PATCH call."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {"fields": []}
        mock_collection.update.return_value = {}
        mock_client.collections.__getitem__.return_value = mock_collection

        schema = {
            "name": "news",
            "fields": [
                {"name": "field_a", "type": "string", "facet": True, "optional": True},
                {"name": "field_b", "type": "int32", "facet": False, "optional": True},
            ],
        }

        result = update_schema(mock_client, schema=schema)

        assert "field_a" in result["added"]
        assert "field_b" in result["added"]
        mock_collection.update.assert_called_once_with({"fields": schema["fields"]})

    def test_sanitizes_sensitive_error_messages(self):
        """Does not expose API keys in error messages."""
        from data_platform.typesense.collection import _sanitize_error

        e = Exception("Connection to host with api_key=abc123 failed")
        sanitized = _sanitize_error(e)
        assert "abc123" not in sanitized
        assert "omitted" in sanitized


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
