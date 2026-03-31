"""Thumbnail extraction from video using ffmpeg.

Pure wrapper around ffmpeg subprocess — no database or storage I/O.
"""

import subprocess
from dataclasses import dataclass

from loguru import logger

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 360
DEFAULT_TIMEOUT = 30


class ThumbnailExtractionError(Exception):
    """Raised when frame extraction fails."""


@dataclass
class ThumbnailExtractionResult:
    """Value object for extraction result."""

    image_bytes: bytes
    width: int
    height: int
    format: str


ALLOWED_SCHEMES = ("http://", "https://")


def _validate_video_url(video_url: str) -> None:
    """Validate that video URL uses a safe scheme.

    Prevents SSRF via ffmpeg protocols (file://, concat:, data:, etc).

    Raises:
        ThumbnailExtractionError: If URL scheme is not HTTP(S).
    """
    if not video_url.lower().startswith(ALLOWED_SCHEMES):
        raise ThumbnailExtractionError(f"Invalid URL scheme: {video_url[:50]}")


def build_ffmpeg_command(video_url: str, width: int, height: int) -> list[str]:
    """Build ffmpeg command to extract first frame as JPEG.

    Args:
        video_url: HTTP(S) URL to the video file.
        width: Target width in pixels.
        height: Target height in pixels.

    Returns:
        List of command arguments for subprocess.
    """
    return [
        "ffmpeg",
        "-nostdin",
        "-i",
        video_url,
        "-vframes",
        "1",
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "image2",
        "-c:v",
        "mjpeg",
        "pipe:1",
    ]


def extract_first_frame(
    video_url: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> ThumbnailExtractionResult:
    """Extract the first frame from a video URL as a resized JPEG.

    Uses ffmpeg to read only the first frame from the remote URL,
    avoiding downloading the entire video file. Output is piped
    to stdout to avoid temp files.

    Args:
        video_url: HTTP(S) URL to the video file.
        width: Target width in pixels.
        height: Target height in pixels.
        timeout_seconds: Maximum time to wait for ffmpeg.

    Returns:
        ThumbnailExtractionResult with JPEG bytes.

    Raises:
        ThumbnailExtractionError: If ffmpeg fails or times out.
    """
    _validate_video_url(video_url)
    cmd = build_ffmpeg_command(video_url, width, height)
    logger.info(f"Extracting thumbnail from {video_url} ({width}x{height})")

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as e:
        raise ThumbnailExtractionError(
            f"ffmpeg timeout after {timeout_seconds}s for {video_url}"
        ) from e

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise ThumbnailExtractionError(
            f"ffmpeg exit code {result.returncode} for {video_url}: {stderr[:200]}"
        )

    if not result.stdout:
        raise ThumbnailExtractionError(f"ffmpeg produced empty output for {video_url}")

    logger.info(f"Extracted {len(result.stdout)} bytes from {video_url}")

    return ThumbnailExtractionResult(
        image_bytes=result.stdout,
        width=width,
        height=height,
        format="jpeg",
    )
