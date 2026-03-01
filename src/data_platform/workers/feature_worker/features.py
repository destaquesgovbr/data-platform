"""Pure feature computation functions (no I/O, easily testable)."""

from datetime import datetime

import textstat


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
