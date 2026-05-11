"""Unit tests for Typesense orphan detection."""

import json
from unittest.mock import MagicMock, patch

from data_platform.jobs.typesense.orphan_detection import (
    delete_orphans,
    find_orphans,
    get_pg_unique_ids,
    get_typesense_doc_ids,
)


class TestFindOrphans:
    def test_returns_ids_in_typesense_not_in_pg(self):
        ts_ids = {"a", "b", "c", "d"}
        pg_ids = {"a", "c"}
        assert find_orphans(ts_ids, pg_ids) == {"b", "d"}

    def test_returns_empty_when_all_exist(self):
        ts_ids = {"a", "b", "c"}
        pg_ids = {"a", "b", "c", "d"}
        assert find_orphans(ts_ids, pg_ids) == set()

    def test_handles_empty_typesense(self):
        assert find_orphans(set(), {"a", "b"}) == set()

    def test_handles_empty_pg(self):
        ts_ids = {"a", "b"}
        assert find_orphans(ts_ids, set()) == {"a", "b"}


class TestGetTypesenseDocIds:
    def test_parses_jsonl_export(self):
        mock_client = MagicMock()
        export_lines = "\n".join([
            json.dumps({"id": "doc-1"}),
            json.dumps({"id": "doc-2"}),
            json.dumps({"id": "doc-3"}),
        ])
        mock_client.collections.__getitem__.return_value.documents.export.return_value = export_lines

        result = get_typesense_doc_ids(mock_client, "news")

        assert result == {"doc-1", "doc-2", "doc-3"}
        mock_client.collections.__getitem__.return_value.documents.export.assert_called_once_with(
            {"include_fields": "id"}
        )

    def test_handles_empty_collection(self):
        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value.documents.export.return_value = ""

        result = get_typesense_doc_ids(mock_client, "news")

        assert result == set()


class TestGetPgUniqueIds:
    @patch("data_platform.jobs.typesense.orphan_detection.create_engine")
    def test_returns_set_of_ids(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("id-1",), ("id-2",), ("id-3",)]
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_create_engine.return_value = mock_engine

        result = get_pg_unique_ids("postgresql://test")

        assert result == {"id-1", "id-2", "id-3"}
        mock_engine.dispose.assert_called_once()


class TestDeleteOrphans:
    def test_calls_delete_for_each_orphan(self):
        mock_client = MagicMock()
        mock_docs = mock_client.collections.__getitem__.return_value.documents.__getitem__
        mock_docs.return_value.delete.return_value = {"id": "x"}

        result = delete_orphans(mock_client, "news", {"orphan-1", "orphan-2"})

        assert result["deleted"] == 2
        assert result["errors"] == 0

    def test_handles_404_as_success(self):
        from typesense.exceptions import ObjectNotFound

        mock_client = MagicMock()
        mock_docs = mock_client.collections.__getitem__.return_value.documents.__getitem__
        mock_docs.return_value.delete.side_effect = ObjectNotFound("Not found")

        result = delete_orphans(mock_client, "news", {"orphan-1"})

        assert result["deleted"] == 0
        assert result["not_found"] == 1
        assert result["errors"] == 0

    def test_counts_errors_on_exception(self):
        mock_client = MagicMock()
        mock_docs = mock_client.collections.__getitem__.return_value.documents.__getitem__
        mock_docs.return_value.delete.side_effect = Exception("Connection refused")

        result = delete_orphans(mock_client, "news", {"orphan-1"})

        assert result["deleted"] == 0
        assert result["errors"] == 1

    def test_dry_run_does_not_delete(self):
        mock_client = MagicMock()

        result = delete_orphans(mock_client, "news", {"orphan-1", "orphan-2"}, dry_run=True)

        mock_client.collections.__getitem__.return_value.documents.__getitem__.return_value.delete.assert_not_called()
        assert result["would_delete"] == 2

    def test_returns_summary_dict(self):
        mock_client = MagicMock()
        mock_docs = mock_client.collections.__getitem__.return_value.documents.__getitem__
        mock_docs.return_value.delete.return_value = {"id": "x"}

        result = delete_orphans(mock_client, "news", {"a", "b", "c"})

        assert "deleted" in result
        assert "errors" in result
        assert "not_found" in result
