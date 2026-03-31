"""Unit tests for thumbnail extractor (ffmpeg wrapper)."""

import subprocess
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from data_platform.workers.thumbnail_worker.extractor import (
    ThumbnailExtractionError,
    ThumbnailExtractionResult,
    build_ffmpeg_command,
    extract_first_frame,
)

# Minimal valid JPEG: SOI marker (0xFFD8) + APP0 + EOI marker (0xFFD9)
FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"


class TestBuildFfmpegCommand:
    """Tests for build_ffmpeg_command (pure function)."""

    def test_includes_input_url(self) -> None:
        cmd = build_ffmpeg_command("http://example.com/video.mp4", 640, 360)
        assert "http://example.com/video.mp4" in cmd

    def test_includes_scale_dimensions(self) -> None:
        cmd = build_ffmpeg_command("http://example.com/video.mp4", 640, 360)
        joined = " ".join(cmd)
        assert "scale=640:360" in joined

    def test_extracts_single_frame(self) -> None:
        cmd = build_ffmpeg_command("http://example.com/video.mp4", 640, 360)
        assert "-vframes" in cmd
        idx = cmd.index("-vframes")
        assert cmd[idx + 1] == "1"

    def test_outputs_jpeg_to_pipe(self) -> None:
        cmd = build_ffmpeg_command("http://example.com/video.mp4", 640, 360)
        assert "pipe:1" in cmd
        assert "mjpeg" in cmd

    def test_custom_dimensions(self) -> None:
        cmd = build_ffmpeg_command("http://example.com/video.mp4", 320, 180)
        joined = " ".join(cmd)
        assert "scale=320:180" in joined


class TestExtractFirstFrame:
    """Tests for extract_first_frame (subprocess wrapper)."""

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_returns_jpeg_bytes(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout=FAKE_JPEG_BYTES, stderr=b""
        )
        result = extract_first_frame("http://example.com/video.mp4")

        assert isinstance(result, ThumbnailExtractionResult)
        assert result.image_bytes[:2] == b"\xff\xd8"
        assert result.width == 640
        assert result.height == 360
        assert result.format == "jpeg"

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_custom_dimensions(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout=FAKE_JPEG_BYTES, stderr=b""
        )
        result = extract_first_frame("http://example.com/video.mp4", width=320, height=180)

        assert result.width == 320
        assert result.height == 180

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_timeout_raises_extraction_error(self, mock_run) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30)

        with pytest.raises(ThumbnailExtractionError, match="timeout"):
            extract_first_frame("http://example.com/video.mp4")

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_nonzero_exit_code_raises_extraction_error(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"Error decoding video"
        )

        with pytest.raises(ThumbnailExtractionError, match="exit code 1"):
            extract_first_frame("http://example.com/video.mp4")

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_empty_output_raises_extraction_error(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        with pytest.raises(ThumbnailExtractionError, match="empty"):
            extract_first_frame("http://example.com/video.mp4")

    @patch("data_platform.workers.thumbnail_worker.extractor.subprocess.run")
    def test_passes_timeout_to_subprocess(self, mock_run) -> None:
        mock_run.return_value = CompletedProcess(
            args=[], returncode=0, stdout=FAKE_JPEG_BYTES, stderr=b""
        )
        extract_first_frame("http://example.com/video.mp4", timeout_seconds=60)

        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 60
