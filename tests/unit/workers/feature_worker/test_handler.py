"""
Unit tests for feature_worker handler.

Tests handle_feature_computation() orchestration:
- fetch article → compute features → upsert
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from data_platform.workers.feature_worker.handler import handle_feature_computation


@pytest.fixture
def mock_pg():
    pg = MagicMock()
    pg.get_connection.return_value = MagicMock()
    pg.put_connection = MagicMock()
    pg.upsert_features = MagicMock(return_value=True)
    return pg


def _make_cursor(row=None):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cursor.close = MagicMock()
    return cursor


class TestHandleFeatureComputation:
    def test_returns_computed_status_for_existing_article(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Conteúdo do artigo com várias palavras para teste.",
                "https://example.com/img.jpg",
                None,
                datetime(2024, 6, 17, 14, 0, 0, tzinfo=timezone.utc),
                None,  # entities
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["status"] == "computed"
        assert result["unique_id"] == "abc123"
        assert isinstance(result["features"], list)
        assert "word_count" in result["features"]
        assert "has_image" in result["features"]
        assert "content_annotations" in result["features"]
        assert "annotations_source_hash" in result["features"]

    def test_returns_not_found_for_missing_article(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=None)
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("nonexistent", mock_pg)

        assert result["status"] == "not_found"
        assert result["unique_id"] == "nonexistent"
        mock_pg.upsert_features.assert_not_called()

    def test_calls_upsert_features_with_computed_dict(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Texto com conteúdo para feature computation.",
                None,
                None,
                datetime(2024, 6, 17, 9, 0, 0),
                None,
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        mock_pg.upsert_features.assert_called_once()
        call_args = mock_pg.upsert_features.call_args
        unique_id_arg = call_args[0][0]
        features_arg = call_args[0][1]

        assert unique_id_arg == "abc123"
        assert isinstance(features_arg, dict)
        assert features_arg["word_count"] > 0
        assert features_arg["has_image"] is False

    def test_propagates_upsert_error(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1), None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn
        mock_pg.upsert_features.side_effect = Exception("DB error during upsert")

        with pytest.raises(Exception, match="DB error during upsert"):
            handle_feature_computation("abc123", mock_pg)

    def test_connection_returned_to_pool_on_success(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1), None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        mock_pg.put_connection.assert_called_once_with(conn)

    def test_connection_returned_to_pool_when_not_found(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=None)
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("missing", mock_pg)

        mock_pg.put_connection.assert_called_once_with(conn)

    def test_features_include_publication_fields_when_published_at_set(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Texto de artigo.",
                None,
                None,
                datetime(2024, 6, 17, 14, 30, 0, tzinfo=timezone.utc),
                None,
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "publication_hour" in features_arg
        assert features_arg["publication_hour"] == 14
        assert "publication_dow" in features_arg

    def test_features_omit_publication_fields_when_published_at_none(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Texto de artigo.", None, None, None, None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "publication_hour" not in features_arg
        assert "publication_dow" not in features_arg

    def test_content_annotations_derived_from_entities(self, mock_pg):
        """Existing entities in news_features yield inline offsets in the upsert."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "O MEC anunciou novidades hoje cedo de manhã.",
                None,
                None,
                datetime(2024, 1, 1),
                [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}],
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        anns = features_arg["content_annotations"]
        assert anns == [
            {"start": 2, "end": 5, "type": "ORG", "text": "MEC", "canonical_id": "dgb_mec"}
        ]
        assert isinstance(features_arg["annotations_source_hash"], str)

    def test_content_annotations_empty_when_entities_absent(self, mock_pg):
        """No entities (race with enrichment worker) → empty annotations, no crash."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Texto sem entidades.", None, None, datetime(2024, 1, 1), None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["status"] == "computed"
        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert features_arg["content_annotations"] == []

    def test_content_annotations_from_json_string_entities(self, mock_pg):
        """Entities arriving as a JSON-encoded string (driver variance) still parse."""
        import json

        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Lula discursou em Brasília.",
                None,
                None,
                datetime(2024, 1, 1),
                json.dumps([{"text": "Lula", "type": "PER", "canonical_id": "Q8765"}]),
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        anns = features_arg["content_annotations"]
        assert len(anns) == 1
        assert anns[0]["text"] == "Lula"
        assert anns[0]["canonical_id"] == "Q8765"

    def test_upsert_merges_without_dropping_other_keys(self, mock_pg):
        """The handler passes a feature dict; upsert_features merges via JSONB || so
        other pre-existing keys (e.g. entities, sentiment) are preserved upstream.
        Here we assert the handler does not overwrite the whole features object —
        it only adds the keys it computed (incl. content_annotations)."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "O MEC agiu.",
                None,
                None,
                datetime(2024, 1, 1),
                [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}],
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        # The handler must NOT include `entities` in its upsert payload (it only
        # reads them), so the existing entities are never clobbered by the merge.
        assert "entities" not in features_arg
        assert "content_annotations" in features_arg
        assert "word_count" in features_arg
