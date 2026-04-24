"""Unit tests for thumbnail batch job."""

from unittest.mock import Mock, patch

import pandas as pd
from data_platform.jobs.thumbnail.batch import fetch_articles_needing_thumbnails


class TestFetchArticlesNeedingThumbnails:
    """Tests for fetch_articles_needing_thumbnails."""

    @patch("data_platform.jobs.thumbnail.batch.pd.read_sql_query")
    def test_returns_articles_with_video_no_image(self, mock_read_sql) -> None:
        mock_read_sql.return_value = pd.DataFrame(
            {"unique_id": ["a1", "a2"], "video_url": ["http://v1.mp4", "http://v2.mp4"]}
        )
        mock_engine = Mock()

        articles = fetch_articles_needing_thumbnails(mock_engine, batch_size=100)

        assert len(articles) == 2
        assert articles[0]["unique_id"] == "a1"
        assert articles[0]["video_url"] == "http://v1.mp4"

    @patch("data_platform.jobs.thumbnail.batch.pd.read_sql_query")
    def test_returns_empty_list_when_no_articles(self, mock_read_sql) -> None:
        mock_read_sql.return_value = pd.DataFrame(columns=["unique_id", "video_url"])
        mock_engine = Mock()

        articles = fetch_articles_needing_thumbnails(mock_engine, batch_size=100)

        assert articles == []

    @patch("data_platform.jobs.thumbnail.batch.pd.read_sql_query")
    def test_query_excludes_previously_failed(self, mock_read_sql) -> None:
        mock_read_sql.return_value = pd.DataFrame(columns=["unique_id", "video_url"])
        mock_engine = Mock()

        fetch_articles_needing_thumbnails(mock_engine, batch_size=50)

        query_text = str(mock_read_sql.call_args[0][0])
        assert "thumbnail_failed" in query_text

    @patch("data_platform.jobs.thumbnail.batch.pd.read_sql_query")
    def test_query_has_deterministic_order(self, mock_read_sql) -> None:
        """ORDER BY must include tiebreaker for deterministic pagination."""
        mock_read_sql.return_value = pd.DataFrame(columns=["unique_id", "video_url"])
        mock_engine = Mock()

        fetch_articles_needing_thumbnails(mock_engine, batch_size=10)

        query_text = str(mock_read_sql.call_args[0][0])
        assert "n.unique_id ASC" in query_text

    @patch("data_platform.jobs.thumbnail.batch.pd.read_sql_query")
    def test_respects_batch_size(self, mock_read_sql) -> None:
        mock_read_sql.return_value = pd.DataFrame(columns=["unique_id", "video_url"])
        mock_engine = Mock()

        fetch_articles_needing_thumbnails(mock_engine, batch_size=25)

        params = mock_read_sql.call_args[1].get("params") or mock_read_sql.call_args[0][2]
        assert 25 in params.values() or 25 in params
