"""Pure feature computation functions (no I/O, easily testable)."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any

import textstat

# Word-boundary lookarounds. Python's ``\b`` is unreliable with accented
# characters, so we assert explicitly that the match is not flanked by a
# letter or digit (including the Latin-1 accented range À-ÿ).
_WORD_CHAR = r"[0-9A-Za-zÀ-ÿ]"
_BOUNDARY_BEFORE = rf"(?<!{_WORD_CHAR})"
_BOUNDARY_AFTER = rf"(?!{_WORD_CHAR})"


def compute_word_count(content: str | None) -> int:
    if not content:
        return 0
    return len(content.split())


def compute_char_count(content: str | None) -> int:
    if not content:
        return 0
    return len(content)


def compute_paragraph_count(content: str | None) -> int:
    if not content:
        return 0
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    return len(paragraphs)


def compute_has_image(image_url: str | None) -> bool:
    return bool(image_url)


def compute_has_video(video_url: str | None) -> bool:
    return bool(video_url)


def compute_publication_hour(published_at: datetime) -> int:
    return published_at.hour


def compute_publication_dow(published_at: datetime) -> int:
    # Monday=0, Sunday=6
    return published_at.weekday()


def compute_readability_flesch(content: str | None) -> float | None:
    if not content or len(content.split()) < 10:
        return None
    try:
        return round(textstat.flesch_reading_ease(content), 2)
    except Exception:
        return None


def _fold_codepoint(ch: str) -> str:
    """
    Fold a single original codepoint: NFKD decompose → drop combining marks →
    casefold. May expand (``'ß'`` → ``'ss'``), contract to empty (a standalone
    combining mark), or stay 1:1. Callers must NOT assume length is preserved.
    """
    decomposed = unicodedata.normalize("NFKD", ch)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold()


def _fold_with_map(s: str) -> tuple[str, list[int]]:
    """
    Fold ``s`` for accent/case-insensitive matching, returning the folded string
    plus a map from each folded char position back to the ORIGINAL codepoint
    index that produced it.

    Folding is per original codepoint (NFKD → drop combining → casefold), so it
    is NOT length-preserving in either direction. The index map — not an
    equal-length assumption — is what lets a folded match span be translated back
    to offsets into the original (un-renormalized) string.
    """
    folded: list[str] = []
    idx_map: list[int] = []  # folded position -> original codepoint index
    for i, ch in enumerate(s):
        for fc in _fold_codepoint(ch):
            folded.append(fc)
            idx_map.append(i)
    return "".join(folded), idx_map


def _fold_surface(text: str) -> str:
    """
    Fold an entity surface for matching (same per-codepoint fold as the content).
    Internal whitespace is collapsed to a single space (the regex turns it into
    ``\\s+`` so it tolerates runs of whitespace/newlines in the content).
    """
    folded, _ = _fold_with_map(text)
    return re.sub(r"\s+", " ", folded).strip()


def _surface_pattern(folded_surface: str) -> re.Pattern[str]:
    """Build a word-boundary regex for a folded surface (whitespace → ``\\s+``)."""
    parts = [re.escape(tok) for tok in folded_surface.split(" ")]
    body = r"\s+".join(parts)
    return re.compile(f"{_BOUNDARY_BEFORE}{body}{_BOUNDARY_AFTER}")


def compute_content_annotations(
    content: str | None, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Derive deterministic inline offsets for entity mentions in ``content``.

    Each entity surface (``text``) is matched against an accent/case-folded copy
    of ``content``. Folding is per original codepoint (NFKD → drop combining →
    casefold) and is NOT length-preserving, so an explicit folded→original index
    map (``_fold_with_map``) translates each folded match span back to offsets
    into the *original*, un-renormalized ``content`` — never assume equal length.
    Matching uses word-boundary lookarounds (``\\b`` is unreliable with accents)
    and collapses internal whitespace in the surface to ``\\s+``.

    Overlap resolution is **longest-match-wins, no nesting**: all candidate spans
    are gathered, sorted by ``(start asc, length desc)`` with ties broken by
    entity ``count`` desc then original order, then swept with a cursor that
    accepts a span only when ``start >= cursor`` (and advances ``cursor`` to its
    end). Thus ``Ministério da Educação (MEC)`` wins and the nested ``MEC`` is
    dropped, while a standalone later ``MEC`` still matches.

    Args:
        content: Article body (``news.content``). None/empty → ``[]``.
        entities: ``news_features.features.entities`` list of mention dicts.

    Returns:
        Flat, sorted, non-overlapping list of
        ``{start, end, type, text, canonical_id}`` (canonical_id may be None).
        ``start``/``end``/``text`` index the original ``content`` (the stored
        ``text`` is exactly ``content[start:end]``). Entities not found in the
        content contribute nothing.
    """
    if not content or not entities:
        return []

    folded_content, idx_map = _fold_with_map(content)
    if not folded_content:
        return []

    # Gather all candidate spans. Each candidate carries sort keys for
    # deterministic, idempotent overlap resolution.
    candidates: list[dict[str, Any]] = []
    for order, entity in enumerate(entities):
        if not isinstance(entity, dict):
            continue
        text = entity.get("text")
        if not isinstance(text, str) or not text.strip():
            continue

        folded_surface = _fold_surface(text)
        if not folded_surface:
            continue

        pattern = _surface_pattern(folded_surface)
        entity_type = entity.get("type")
        entity_type = entity_type.strip().upper() if isinstance(entity_type, str) else None
        canonical_id = entity.get("canonical_id")
        if not isinstance(canonical_id, str):
            canonical_id = None
        count = entity.get("count")
        count = count if isinstance(count, int) else 0

        for match in pattern.finditer(folded_content):
            fa, fb = match.start(), match.end()
            # Empty folded match (defensive — surface fold is non-empty here, so
            # fb > fa, but guard anyway).
            if fb <= fa:
                continue
            # Map folded span [fa, fb) back to original codepoint offsets.
            start = idx_map[fa]
            end = idx_map[fb - 1] + 1
            candidates.append(
                {
                    "start": start,
                    "end": end,
                    "length": end - start,
                    "type": entity_type,
                    "text": content[start:end],
                    "canonical_id": canonical_id,
                    "_count": count,
                    "_order": order,
                }
            )

    # Longest-match-wins sweep. Sort by start asc, then length desc, then
    # count desc, then original entity order (stable → idempotent).
    candidates.sort(key=lambda c: (c["start"], -c["length"], -c["_count"], c["_order"]))

    annotations: list[dict[str, Any]] = []
    cursor = 0
    for cand in candidates:
        if cand["start"] < cursor:
            continue
        annotations.append(
            {
                "start": cand["start"],
                "end": cand["end"],
                "type": cand["type"],
                "text": cand["text"],
                "canonical_id": cand["canonical_id"],
            }
        )
        cursor = cand["end"]

    return annotations


def compute_annotations_source_hash(content: str | None, entities: list[dict[str, Any]]) -> str:
    """
    Cheap idempotency hash over the inputs that determine annotations.

    Lets the handler skip recompute when neither content nor the entity surfaces
    / canonical_ids changed. Hashes only the fields that affect the output.
    """
    surfaces = [
        {
            "text": e.get("text"),
            "type": e.get("type"),
            "canonical_id": e.get("canonical_id"),
            "count": e.get("count"),
        }
        for e in entities
        if isinstance(e, dict)
    ]
    payload = json.dumps(
        {"content": content or "", "entities": surfaces},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_all(article: dict) -> dict:
    """Compute all local features for an article.

    Args:
        article: dict with keys: content, image_url, video_url, published_at

    Returns:
        dict ready for JSONB merge via upsert_features()
    """
    content = article.get("content")
    published_at = article.get("published_at")

    features: dict = {
        "word_count": compute_word_count(content),
        "char_count": compute_char_count(content),
        "paragraph_count": compute_paragraph_count(content),
        "has_image": compute_has_image(article.get("image_url")),
        "has_video": compute_has_video(article.get("video_url")),
    }

    if published_at:
        features["publication_hour"] = compute_publication_hour(published_at)
        features["publication_dow"] = compute_publication_dow(published_at)

    flesch = compute_readability_flesch(content)
    if flesch is not None:
        features["readability_flesch"] = flesch

    return features
