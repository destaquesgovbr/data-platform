"""Unit tests for thumbnail generation handler (orchestration)."""

from unittest.mock import Mock

import pytest
from data_platform.workers.thumbnail_worker.extractor import (
    ThumbnailExtractionError,
    ThumbnailExtractionResult,
)
from data_platform.workers.thumbnail_worker.handler import handle_thumbnail_generation

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
FAKE_URL = "https://storage.googleapis.com/bucket/thumbnails/uid_123.jpg"


def _make_article(video_url: str | None = "http://v.mp4", image_url: str | None = None) -> Mock:
    """Create a mock News object."""
    article = Mock()
    article.video_url = video_url
    article.image_url = image_url
    article.unique_id = "uid_123"
    return article


def _make_extraction_result() -> ThumbnailExtractionResult:
    return ThumbnailExtractionResult(image_bytes=FAKE_JPEG, width=640, height=360, format="jpeg")


class TestHandleThumbnailGeneration:
    """Tests for handle_thumbnail_generation."""

    def test_generates_thumbnail_for_eligible_article(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = None
        mock_extractor = Mock(return_value=_make_extraction_result())
        mock_uploader = Mock(return_value=FAKE_URL)
        mock_exists = Mock(return_value=False)

        result = handle_thumbnail_generation(
            "uid_123",
            mock_pg,
            "bucket",
            extractor_fn=mock_extractor,
            uploader_fn=mock_uploader,
            exists_fn=mock_exists,
        )

        assert result["status"] == "generated"
        mock_pg.update.assert_called_once_with("uid_123", {"image_url": FAKE_URL})
        mock_pg.upsert_features.assert_called_once()
        features = mock_pg.upsert_features.call_args[0][1]
        assert features["has_image"] is True
        assert features["thumbnail_generated"] is True

    def test_skips_article_with_existing_image(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article(image_url="http://img.jpg")

        result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")

        assert result["status"] == "skipped"
        mock_pg.update.assert_not_called()

    def test_skips_article_without_video(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article(video_url=None)

        result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")

        assert result["status"] == "skipped"
        mock_pg.update.assert_not_called()

    def test_skips_article_with_empty_video_url(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article(video_url="")

        result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")

        assert result["status"] == "skipped"
        mock_pg.update.assert_not_called()

    def test_not_found_for_missing_article(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = None

        result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")

        assert result["status"] == "not_found"

    def test_idempotent_when_gcs_has_thumbnail(self) -> None:
        """GCS already has thumbnail but DB image_url is NULL — just update DB."""
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = None
        mock_exists = Mock(return_value=True)
        mock_extractor = Mock()

        result = handle_thumbnail_generation(
            "uid_123",
            mock_pg,
            "bucket",
            extractor_fn=mock_extractor,
            exists_fn=mock_exists,
        )

        assert result["status"] == "generated"
        mock_extractor.assert_not_called()  # Should NOT re-extract
        mock_pg.update.assert_called_once()  # Should update DB

    def test_marks_failed_on_extraction_error(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = None
        mock_extractor = Mock(side_effect=ThumbnailExtractionError("ffmpeg failed"))
        mock_exists = Mock(return_value=False)

        result = handle_thumbnail_generation(
            "uid_123",
            mock_pg,
            "bucket",
            extractor_fn=mock_extractor,
            exists_fn=mock_exists,
        )

        assert result["status"] == "error"
        mock_pg.upsert_features.assert_called_once()
        features = mock_pg.upsert_features.call_args[0][1]
        assert features["thumbnail_failed"] is True

    def test_skips_previously_failed_article(self) -> None:
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = {"thumbnail_failed": True}

        result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")

        assert result["status"] == "skipped"
        assert "previously failed" in result.get("reason", "")

    def test_updates_features_before_image_url(self) -> None:
        """Features must be updated before image_url for retry consistency.

        If the order were reversed and update() succeeded but upsert_features()
        failed, the article would be skipped on retry (has image_url) leaving
        has_image=false permanently in the feature store.
        """
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = None
        mock_extractor = Mock(return_value=_make_extraction_result())
        mock_uploader = Mock(return_value=FAKE_URL)
        mock_exists = Mock(return_value=False)

        call_order = []
        mock_pg.upsert_features.side_effect = lambda *a, **kw: call_order.append("features")
        mock_pg.update.side_effect = lambda *a, **kw: call_order.append("image_url")

        handle_thumbnail_generation(
            "uid_123",
            mock_pg,
            "bucket",
            extractor_fn=mock_extractor,
            uploader_fn=mock_uploader,
            exists_fn=mock_exists,
        )

        assert call_order == ["features", "image_url"], (
            "Features must be updated before image_url for retry consistency"
        )

    def test_db_update_failure_propagates(self) -> None:
        """If DB update fails after upload, exception propagates (not swallowed)."""
        mock_pg = Mock()
        mock_pg.get_by_unique_id.return_value = _make_article()
        mock_pg.get_features.return_value = None
        mock_pg.update.side_effect = RuntimeError("DB connection lost")
        mock_extractor = Mock(return_value=_make_extraction_result())
        mock_uploader = Mock(return_value=FAKE_URL)
        mock_exists = Mock(return_value=False)

        with pytest.raises(RuntimeError, match="DB connection lost"):
            handle_thumbnail_generation(
                "uid_123",
                mock_pg,
                "bucket",
                extractor_fn=mock_extractor,
                uploader_fn=mock_uploader,
                exists_fn=mock_exists,
            )
