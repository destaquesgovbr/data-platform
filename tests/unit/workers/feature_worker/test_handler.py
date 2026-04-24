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
            row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1))
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn
        mock_pg.upsert_features.side_effect = Exception("DB error during upsert")

        with pytest.raises(Exception, match="DB error during upsert"):
            handle_feature_computation("abc123", mock_pg)

    def test_connection_returned_to_pool_on_success(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1))
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
            row=("abc123", "Texto de artigo.", None, None, None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "publication_hour" not in features_arg
        assert "publication_dow" not in features_arg
