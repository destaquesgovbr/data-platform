"""Unit tests for feature computation functions."""

from datetime import datetime, timezone

import pytest

from data_platform.workers.feature_worker.features import (
    compute_all,
    compute_char_count,
    compute_content_annotations,
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


class TestComputeContentAnnotations:
    """Tests for compute_content_annotations() — deterministic offset derivation."""

    def test_simple_single_occurrence(self):
        content = "O MEC anunciou novidades."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}]
        result = compute_content_annotations(content, entities)
        assert result == [
            {"start": 2, "end": 5, "type": "ORG", "text": "MEC", "canonical_id": "dgb_mec"}
        ]
        # Verify the slice matches the original surface exactly.
        assert content[2:5] == "MEC"

    def test_nested_overlap_longest_match_wins(self):
        """'Ministério da Educação (MEC)' engulfs the nested 'MEC'; a later
        standalone 'MEC' still matches."""
        content = "O Ministério da Educação (MEC) agiu. Depois o MEC voltou."
        entities = [
            {"text": "Ministério da Educação (MEC)", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
        ]
        result = compute_content_annotations(content, entities)
        # First span = the long surface; the nested MEC inside it is dropped.
        long_start = content.index("Ministério da Educação (MEC)")
        long_end = long_start + len("Ministério da Educação (MEC)")
        standalone_start = content.index("MEC", long_end)
        assert result == [
            {
                "start": long_start,
                "end": long_end,
                "type": "ORG",
                "text": "Ministério da Educação (MEC)",
                "canonical_id": "dgb_mec",
            },
            {
                "start": standalone_start,
                "end": standalone_start + 3,
                "type": "ORG",
                "text": "MEC",
                "canonical_id": "dgb_mec",
            },
        ]

    def test_multiple_occurrences_all_marked(self):
        content = "Lula falou. Lula repetiu. Lula concluiu."
        entities = [{"text": "Lula", "type": "PER", "canonical_id": "Q8765"}]
        result = compute_content_annotations(content, entities)
        starts = [a["start"] for a in result]
        assert starts == [0, 12, 26]
        for a in result:
            assert content[a["start"] : a["end"]] == "Lula"

    def test_accent_and_case_insensitive_preserves_offsets(self):
        """Match is accent/case-insensitive but offsets/text reflect the original."""
        content = "A EDUCACAO e a educação importam."
        entities = [{"text": "Educação", "type": "POLICY", "canonical_id": None}]
        result = compute_content_annotations(content, entities)
        # Both 'EDUCACAO' (no accent, uppercase) and 'educação' (lowercase, accent) match.
        assert len(result) == 2
        first, second = result
        assert content[first["start"] : first["end"]] == "EDUCACAO"
        assert content[second["start"] : second["end"]] == "educação"
        assert first["type"] == "POLICY"
        assert first["canonical_id"] is None

    def test_word_boundary_prevents_substring_match(self):
        """'MEC' must not match inside 'MECANICA' or 'COMEÇO'."""
        content = "A MECANICA do COMEÇO. Mas o MEC sim."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": None}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert content[result[0]["start"] : result[0]["end"]] == "MEC"

    def test_internal_whitespace_collapsed(self):
        """Multiple spaces / newlines in content between surface words still match."""
        content = "O Ministério   da\nEducação cresceu."
        entities = [{"text": "Ministério da Educação", "type": "ORG", "canonical_id": "dgb_mec"}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        # `text` reflects the ORIGINAL slice (with the real whitespace run).
        assert result[0]["text"] == "Ministério   da\nEducação"
        assert content[result[0]["start"] : result[0]["end"]] == "Ministério   da\nEducação"

    def test_surface_not_in_content_skipped_silently(self):
        content = "Texto sobre saúde pública."
        entities = [
            {"text": "Bolsa Família", "type": "POLICY", "canonical_id": "dgb_bf"},
            {"text": "saúde", "type": "POLICY", "canonical_id": None},
        ]
        result = compute_content_annotations(content, entities)
        # Only 'saúde' is present.
        assert len(result) == 1
        assert result[0]["text"] == "saúde"

    def test_output_is_flat_sorted_non_overlapping(self):
        content = "Brasília recebeu Lula e o MEC na quarta."
        entities = [
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "Lula", "type": "PER", "canonical_id": "Q8765"},
            {"text": "Brasília", "type": "LOC", "canonical_id": "Q2844"},
        ]
        result = compute_content_annotations(content, entities)
        starts = [a["start"] for a in result]
        assert starts == sorted(starts)
        # No overlap.
        for prev, nxt in zip(result, result[1:], strict=False):
            assert prev["end"] <= nxt["start"]

    def test_idempotent_same_input_same_output(self):
        content = "O Ministério da Educação (MEC) e o MEC."
        entities = [
            {"text": "Ministério da Educação (MEC)", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
        ]
        first = compute_content_annotations(content, entities)
        second = compute_content_annotations(content, entities)
        assert first == second

    def test_empty_entities_returns_empty(self):
        assert compute_content_annotations("Algum texto.", []) == []

    def test_empty_content_returns_empty(self):
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": None}]
        assert compute_content_annotations("", entities) == []
        assert compute_content_annotations(None, entities) == []

    def test_tie_break_equal_span_by_count_then_order(self):
        """When two entities match the exact same span, higher count wins."""
        content = "O MEC agiu."
        entities = [
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_a", "count": 1},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_b", "count": 9},
        ]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert result[0]["canonical_id"] == "dgb_b"

    def test_missing_canonical_id_defaults_null(self):
        content = "O MEC agiu."
        entities = [{"text": "MEC", "type": "ORG"}]
        result = compute_content_annotations(content, entities)
        assert result[0]["canonical_id"] is None
