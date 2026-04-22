"""Unit tests for feature computation functions."""

from datetime import datetime, timezone

import pytest

from data_platform.workers.feature_worker.features import (
    compute_all,
    compute_char_count,
    compute_has_image,
    compute_has_video,
    compute_paragraph_count,
    compute_publication_dow,
    compute_publication_hour,
    compute_readability_flesch,
    compute_word_count,
)


class TestComputeWordCount:
    def test_normal_text(self):
        assert compute_word_count("Hello world foo bar") == 4

    def test_empty_content(self):
        assert compute_word_count(None) == 0
        assert compute_word_count("") == 0

    def test_multiline(self):
        assert compute_word_count("Hello\nworld\nfoo") == 3


class TestComputeCharCount:
    def test_normal_text(self):
        assert compute_char_count("Hello") == 5

    def test_empty(self):
        assert compute_char_count(None) == 0
        assert compute_char_count("") == 0


class TestComputeParagraphCount:
    def test_single_paragraph(self):
        assert compute_paragraph_count("One paragraph") == 1

    def test_multiple_paragraphs(self):
        assert compute_paragraph_count("First\n\nSecond\n\nThird") == 3

    def test_empty(self):
        assert compute_paragraph_count(None) == 0
        assert compute_paragraph_count("") == 0

    def test_blank_paragraphs_ignored(self):
        assert compute_paragraph_count("First\n\n\n\nSecond") == 2


class TestComputeHasImage:
    def test_with_url(self):
        assert compute_has_image("https://example.com/img.jpg") is True

    def test_without_url(self):
        assert compute_has_image(None) is False
        assert compute_has_image("") is False


class TestComputeHasVideo:
    def test_with_url(self):
        assert compute_has_video("https://example.com/vid.mp4") is True

    def test_without_url(self):
        assert compute_has_video(None) is False
        assert compute_has_video("") is False


class TestComputePublicationHour:
    def test_utc_hour(self):
        dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert compute_publication_hour(dt) == 14

    def test_midnight(self):
        dt = datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert compute_publication_hour(dt) == 0

    def test_none_raises(self):
        """None input raises AttributeError — callers must guard with `if published_at`."""
        with pytest.raises(AttributeError):
            compute_publication_hour(None)


class TestComputePublicationDow:
    def test_monday(self):
        dt = datetime(2024, 6, 17, 12, 0, 0)  # Monday
        assert compute_publication_dow(dt) == 0

    def test_sunday(self):
        dt = datetime(2024, 6, 16, 12, 0, 0)  # Sunday
        assert compute_publication_dow(dt) == 6

    def test_none_raises(self):
        """None input raises AttributeError — callers must guard with `if published_at`."""
        with pytest.raises(AttributeError):
            compute_publication_dow(None)


class TestComputeReadabilityFlesch:
    def test_normal_text(self):
        text = "Este é um texto simples em português. " * 5
        result = compute_readability_flesch(text)
        assert result is not None
        assert isinstance(result, float)

    def test_empty_content(self):
        assert compute_readability_flesch(None) is None
        assert compute_readability_flesch("") is None

    def test_short_text(self):
        assert compute_readability_flesch("Curto") is None


class TestComputeAll:
    def test_complete_article(self):
        article = {
            "content": "Este é o conteúdo do artigo. " * 5,
            "image_url": "https://example.com/img.jpg",
            "video_url": None,
            "published_at": datetime(2024, 6, 17, 14, 30, 0, tzinfo=timezone.utc),
        }
        features = compute_all(article)

        assert features["word_count"] > 0
        assert features["char_count"] > 0
        assert features["paragraph_count"] >= 1
        assert features["has_image"] is True
        assert features["has_video"] is False
        assert features["publication_hour"] == 14
        assert features["publication_dow"] == 0  # Monday

    def test_minimal_article(self):
        article = {"content": None, "image_url": None, "video_url": None}
        features = compute_all(article)

        assert features["word_count"] == 0
        assert features["has_image"] is False
        assert "publication_hour" not in features
        assert "readability_flesch" not in features

    def test_explicit_none_published_at(self):
        """Explicit published_at=None behaves same as missing key."""
        article = {"content": "Some text.", "image_url": None, "video_url": None, "published_at": None}
        features = compute_all(article)

        assert "publication_hour" not in features
        assert "publication_dow" not in features
