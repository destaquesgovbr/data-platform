"""Thumbnail generation handler — orchestrates fetch, extract, upload, update."""

from collections.abc import Callable
from typing import Any

from loguru import logger

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.thumbnail_worker.extractor import (
    ThumbnailExtractionError,
    extract_first_frame,
)
from data_platform.workers.thumbnail_worker.storage import (
    build_public_url,
    build_thumbnail_gcs_path,
    thumbnail_exists,
    upload_thumbnail,
)


def _is_eligible(article: Any) -> tuple[bool, str]:
    """Check if article is eligible for thumbnail generation.

    Args:
        article: News object with video_url and image_url attributes.

    Returns:
        Tuple of (eligible, reason).
    """
    if article.image_url:
        return False, "already has image_url"
    if not article.video_url:
        return False, "no video_url"
    return True, ""


def handle_thumbnail_generation(
    unique_id: str,
    pg: PostgresManager,
    bucket_name: str,
    extractor_fn: Callable = extract_first_frame,
    uploader_fn: Callable = upload_thumbnail,
    exists_fn: Callable = thumbnail_exists,
) -> dict[str, Any]:
    """Orchestrate thumbnail generation for a single article.

    Steps:
        1. Fetch article from PostgreSQL
        2. Check eligibility (has video_url, no image_url)
        3. Check if previously failed
        4. Check idempotency (thumbnail already in GCS?)
        5. Extract first frame via ffmpeg
        6. Upload to GCS
        7. Update image_url in news table
        8. Update features in news_features

    Args:
        unique_id: Article unique_id.
        pg: PostgresManager instance.
        bucket_name: GCS bucket name.
        extractor_fn: Frame extraction callable (DI for testing).
        uploader_fn: GCS upload callable (DI for testing).
        exists_fn: GCS existence check callable (DI for testing).

    Returns:
        Dict with status and details.
    """
    # 1. Fetch article
    article = pg.get_by_unique_id(unique_id)
    if not article:
        logger.warning(f"Article {unique_id} not found")
        return {"status": "not_found", "unique_id": unique_id}

    # 2. Check eligibility
    eligible, reason = _is_eligible(article)
    if not eligible:
        logger.debug(f"Skipping {unique_id}: {reason}")
        return {"status": "skipped", "unique_id": unique_id, "reason": reason}

    # 3. Check if previously failed
    features = pg.get_features(unique_id)
    if features and features.get("thumbnail_failed"):
        logger.debug(f"Skipping {unique_id}: previously failed")
        return {
            "status": "skipped",
            "unique_id": unique_id,
            "reason": "previously failed",
        }

    # 4. Check idempotency — thumbnail already in GCS?
    gcs_path = build_thumbnail_gcs_path(unique_id)
    public_url = build_public_url(bucket_name, gcs_path)
    already_in_gcs = exists_fn(bucket_name, unique_id)

    if not already_in_gcs:
        # 5. Extract first frame
        try:
            result = extractor_fn(article.video_url)
        except ThumbnailExtractionError as e:
            logger.error(f"Extraction failed for {unique_id}: {e}")
            pg.upsert_features(unique_id, {"thumbnail_failed": True})
            return {"status": "error", "unique_id": unique_id, "error": str(e)}

        # 6. Upload to GCS
        public_url = uploader_fn(bucket_name, unique_id, result.image_bytes)

    # 7. Update image_url in news table
    pg.update(unique_id, {"image_url": public_url})

    # 8. Update features
    pg.upsert_features(unique_id, {"has_image": True, "thumbnail_generated": True})

    logger.info(f"Thumbnail {'recovered' if already_in_gcs else 'generated'} for {unique_id}")
    return {"status": "generated", "unique_id": unique_id, "url": public_url}
