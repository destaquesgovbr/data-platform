"""Unit tests for Bronze Writer."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from data_platform.workers.bronze_writer.storage import build_gcs_path


class TestBuildGcsPath:
    def test_path_generation(self):
        dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        path = build_gcs_path("abc123", dt)
        assert path == "bronze/news/2024/06/15/abc123.json"

    def test_path_single_digit_month(self):
        dt = datetime(2024, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
        path = build_gcs_path("xyz789", dt)
        assert path == "bronze/news/2024/01/05/xyz789.json"

    def test_idempotent(self):
        dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        path1 = build_gcs_path("abc123", dt)
        path2 = build_gcs_path("abc123", dt)
        assert path1 == path2


class TestHandleBronzeWrite:
    @patch("data_platform.workers.bronze_writer.handler.write_to_gcs")
    @patch.dict("os.environ", {"GCS_BUCKET": "test-bucket"})
    def test_successful_write(self, mock_gcs):
        from data_platform.workers.bronze_writer.handler import handle_bronze_write

        pg = MagicMock()
        conn = MagicMock()
        pg.get_connection.return_value = conn
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = {
            "unique_id": "abc123",
            "published_at": datetime(2024, 6, 15, tzinfo=timezone.utc),
            "title": "Test",
            "content": "Content",
        }

        result = handle_bronze_write("abc123", pg)

        assert result["status"] == "written"
        assert "bronze/news/2024/06/15/abc123.json" in result["gcs_path"]
        mock_gcs.assert_called_once()

    @patch.dict("os.environ", {"GCS_BUCKET": "test-bucket"})
    def test_article_not_found(self):
        from data_platform.workers.bronze_writer.handler import handle_bronze_write

        pg = MagicMock()
        conn = MagicMock()
        pg.get_connection.return_value = conn
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        result = handle_bronze_write("missing", pg)
        assert result["status"] == "not_found"

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_gcs_bucket(self):
        from data_platform.workers.bronze_writer.handler import handle_bronze_write

        pg = MagicMock()
        result = handle_bronze_write("abc123", pg)
        assert result["status"] == "error"
        assert "GCS_BUCKET" in result["reason"]
