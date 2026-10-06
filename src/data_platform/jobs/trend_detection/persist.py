"""persist.py — snapshot de entity_trending_scores no PostgreSQL.

Cada execução grava o seu ranking e apaga o das execuções anteriores, na mesma
transação: a tabela guarda um único computed_at (o leitor nunca vê dado parcial).
"""

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

_UPSERT_SQL = text("""
    INSERT INTO entity_trending_scores
        (entity_id, canonical_name, type, trending_score, volume_ratio,
         window_count, window_agencies, baseline_count, baseline_agencies, computed_at)
    VALUES
        (:entity_id, :canonical_name, :type, :score, :volume_ratio,
         :window_count, :window_agencies, :baseline_count, :baseline_agencies, NOW())
    ON CONFLICT (entity_id) DO UPDATE SET
        trending_score    = EXCLUDED.trending_score,
        volume_ratio      = EXCLUDED.volume_ratio,
        window_count      = EXCLUDED.window_count,
        window_agencies   = EXCLUDED.window_agencies,
        baseline_count    = EXCLUDED.baseline_count,
        baseline_agencies = EXCLUDED.baseline_agencies,
        computed_at       = EXCLUDED.computed_at
""")

# NOW() é o início da transação: as linhas gravadas pelo upsert acima têm
# computed_at = NOW() e ficam; só as de execuções anteriores saem.
_DELETE_STALE_SQL = text("DELETE FROM entity_trending_scores WHERE computed_at < NOW()")


def _row_params(entity_id: str, score: float, s: dict) -> dict:
    return {
        "entity_id": entity_id,
        "canonical_name": s["canonical_name"],
        "type": s.get("entity_type") or "",
        "score": score,
        "volume_ratio": s["volume_ratio"],
        "window_count": s.get("window_count") or 0,
        "window_agencies": s.get("window_agencies") or 0,
        "baseline_count": s.get("baseline_count") or 0,
        "baseline_agencies": s.get("baseline_agencies") or 0,
    }


def upsert_trending_scores(
    db_url: str,
    scores: list[tuple[str, float]],
    entity_stats: dict,
) -> int:
    """Substitui o snapshot de entity_trending_scores. Retorna o número de linhas gravadas.

    - Sem entity_stats (falta de dado), não toca a tabela: o snapshot anterior fica e
      envelhece, e a idade de max(computed_at) denuncia o problema.
    - Com entity_stats e scores vazios, o snapshot fica vazio (nada em alta).
    """
    if not entity_stats:
        logger.warning("entity_trending_scores: snapshot sem entity_stats; tabela mantida")
        return 0

    params = []
    for entity_id, score in scores:
        s = entity_stats.get(entity_id)
        if not s or not s.get("canonical_name"):
            continue
        params.append(_row_params(entity_id, score, s))

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            if params:
                conn.execute(_UPSERT_SQL, params)
            deleted = conn.execute(_DELETE_STALE_SQL).rowcount
    finally:
        engine.dispose()

    logger.info(
        "entity_trending_scores: %d entidades gravadas, %d linhas antigas removidas",
        len(params),
        deleted,
    )
    return len(params)
