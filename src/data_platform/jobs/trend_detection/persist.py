"""persist.py — UPSERT de entity_trending_scores no PostgreSQL."""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

_UPSERT_SQL = text("""
    INSERT INTO entity_trending_scores
        (entity_id, canonical_name, type, trending_score, volume_ratio,
         window_count, window_agencies, computed_at)
    VALUES
        (:entity_id, :canonical_name, :type, :score, :volume_ratio,
         :window_count, :window_agencies, NOW())
    ON CONFLICT (entity_id) DO UPDATE SET
        trending_score  = EXCLUDED.trending_score,
        volume_ratio    = EXCLUDED.volume_ratio,
        window_count    = EXCLUDED.window_count,
        window_agencies = EXCLUDED.window_agencies,
        computed_at     = EXCLUDED.computed_at
""")


def upsert_trending_scores(
    db_url: str,
    scores: list[tuple[str, float]],
    entity_stats: dict,
) -> int:
    """Faz UPSERT de entity_trending_scores. Retorna número de linhas processadas."""
    if not scores:
        return 0

    engine = create_engine(db_url, poolclass=NullPool)
    count = 0
    try:
        with engine.begin() as conn:
            for entity_id, score in scores:
                s = entity_stats.get(entity_id)
                if not s or not s.get("canonical_name"):
                    continue
                volume_ratio = s["window_daily"] / s["baseline_daily"]
                conn.execute(
                    _UPSERT_SQL,
                    {
                        "entity_id": entity_id,
                        "canonical_name": s["canonical_name"],
                        "type": s.get("entity_type") or "",
                        "score": score,
                        "volume_ratio": volume_ratio,
                        "window_count": s.get("window_count") or 0,
                        "window_agencies": s.get("window_agencies") or 0,
                    },
                )
                count += 1
    finally:
        engine.dispose()

    logger.info("entity_trending_scores: %d entidades atualizadas", count)
    return count
