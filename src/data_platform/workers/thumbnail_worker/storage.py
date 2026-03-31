"""GCS storage operations for video thumbnails."""

from google.cloud import storage as gcs_storage
from loguru import logger

DEFAULT_PREFIX = "thumbnails"
CACHE_CONTROL = "public, max-age=86400"


def build_thumbnail_gcs_path(unique_id: str, prefix: str = DEFAULT_PREFIX) -> str:
    """Build GCS object path for a thumbnail.

    Args:
        unique_id: Article unique_id.
        prefix: GCS path prefix.

    Returns:
        GCS object path (e.g. "thumbnails/article_123.jpg").
    """
    return f"{prefix}/{unique_id}.jpg"


def build_public_url(bucket_name: str, gcs_path: str) -> str:
    """Build public URL for a GCS object.

    Args:
        bucket_name: GCS bucket name.
        gcs_path: Object path within the bucket.

    Returns:
        Public HTTPS URL.
    """
    return f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"


def upload_thumbnail(
    bucket_name: str,
    unique_id: str,
    image_bytes: bytes,
    gcs_client: gcs_storage.Client | None = None,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    """Upload JPEG thumbnail to GCS and return public URL.

    Args:
        bucket_name: GCS bucket name.
        unique_id: Article unique_id.
        image_bytes: JPEG image bytes.
        gcs_client: Optional GCS client (for DI/testing).
        prefix: GCS path prefix.

    Returns:
        Public URL of the uploaded thumbnail.
    """
    client = gcs_client or gcs_storage.Client()
    gcs_path = build_thumbnail_gcs_path(unique_id, prefix)

    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)
    blob.cache_control = CACHE_CONTROL
    blob.upload_from_string(image_bytes, content_type="image/jpeg")

    public_url = build_public_url(bucket_name, gcs_path)
    logger.info(f"Uploaded thumbnail for {unique_id} to {public_url}")

    return public_url


def thumbnail_exists(
    bucket_name: str,
    unique_id: str,
    gcs_client: gcs_storage.Client | None = None,
    prefix: str = DEFAULT_PREFIX,
) -> bool:
    """Check if thumbnail already exists in GCS.

    Args:
        bucket_name: GCS bucket name.
        unique_id: Article unique_id.
        gcs_client: Optional GCS client (for DI/testing).
        prefix: GCS path prefix.

    Returns:
        True if thumbnail exists in GCS.
    """
    client = gcs_client or gcs_storage.Client()
    gcs_path = build_thumbnail_gcs_path(unique_id, prefix)

    bucket = client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    return blob.exists()
