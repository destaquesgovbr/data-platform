"""Unit tests for thumbnail GCS storage."""

from unittest.mock import Mock

from data_platform.workers.thumbnail_worker.storage import (
    build_public_url,
    build_thumbnail_gcs_path,
    thumbnail_exists,
    upload_thumbnail,
)


class TestBuildThumbnailGcsPath:
    """Tests for build_thumbnail_gcs_path (pure function)."""

    def test_returns_correct_path(self) -> None:
        path = build_thumbnail_gcs_path("minha-noticia_abc123")
        assert path == "thumbnails/minha-noticia_abc123.jpg"

    def test_custom_prefix(self) -> None:
        path = build_thumbnail_gcs_path("article_123", prefix="thumbs")
        assert path == "thumbs/article_123.jpg"


class TestBuildPublicUrl:
    """Tests for build_public_url (pure function)."""

    def test_returns_gcs_public_url(self) -> None:
        url = build_public_url("my-bucket", "thumbnails/article_123.jpg")
        assert url == "https://storage.googleapis.com/my-bucket/thumbnails/article_123.jpg"


class TestUploadThumbnail:
    """Tests for upload_thumbnail (mocked GCS)."""

    def test_uploads_with_correct_content_type(self) -> None:
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        url = upload_thumbnail("my-bucket", "article_123", b"jpeg_data", gcs_client=mock_client)

        mock_blob.upload_from_string.assert_called_once_with(
            b"jpeg_data", content_type="image/jpeg"
        )
        assert "storage.googleapis.com" in url
        assert "article_123" in url

    def test_sets_cache_control(self) -> None:
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        upload_thumbnail("my-bucket", "article_123", b"jpeg_data", gcs_client=mock_client)

        assert mock_blob.cache_control == "public, max-age=86400"

    def test_returns_public_url(self) -> None:
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        url = upload_thumbnail("my-bucket", "article_123", b"jpeg_data", gcs_client=mock_client)

        assert url == "https://storage.googleapis.com/my-bucket/thumbnails/article_123.jpg"


class TestThumbnailExists:
    """Tests for thumbnail_exists (mocked GCS)."""

    def test_returns_true_when_blob_exists(self) -> None:
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_blob.exists.return_value = True
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        assert thumbnail_exists("my-bucket", "article_123", gcs_client=mock_client) is True

    def test_returns_false_when_blob_missing(self) -> None:
        mock_client = Mock()
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_blob.exists.return_value = False
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        assert thumbnail_exists("my-bucket", "article_123", gcs_client=mock_client) is False
