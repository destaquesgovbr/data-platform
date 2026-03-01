"""GCS storage operations for Bronze layer."""

import json
import logging
from datetime import datetime

from google.cloud import storage as gcs

logger = logging.getLogger(__name__)


def build_gcs_path(unique_id: str, published_at: datetime) -> str:
    """Build partitioned GCS path: bronze/news/YYYY/MM/DD/{unique_id}.json"""
    return (
        f"bronze/news/{published_at.strftime('%Y/%m/%d')}/{unique_id}.json"
    )


def write_to_gcs(bucket_name: str, path: str, data: dict) -> None:
    """Write JSON data to GCS.

    Args:
        bucket_name: GCS bucket name
        path: Object path within bucket
        data: Dictionary to serialize as JSON
    """
    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(path)

    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json",
    )
    logger.info(f"Written gs://{bucket_name}/{path}")
