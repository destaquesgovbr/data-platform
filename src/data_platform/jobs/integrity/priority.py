"""Priorização de artigos para verificação de integridade.

Tiers de prioridade baseados na idade do artigo:
  Tier 1: < 3h    → re-check a cada 10 min
  Tier 2: 3-24h   → re-check a cada 1h
  Tier 3: 1-7d    → re-check a cada 6h
  Tier 4: 7-30d   → re-check a cada 24h
  Tier 5: 1-5 meses → re-check a cada 7 dias
"""

import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# (tier, max_age_interval, recheck_interval, batch_limit)
PRIORITY_TIERS = [
    (1, "3 hours", "10 minutes", 200),
    (2, "24 hours", "1 hour", 100),
    (3, "7 days", "6 hours", 50),
    (4, "30 days", "24 hours", 30),
    (5, "5 months", "7 days", 20),
]

PRIORITY_QUERY = text("""
    WITH candidates AS (
        SELECT
            n.unique_id,
            n.url,
            n.image_url,
            n.published_at,
            nf.features -> 'integrity' AS integrity,
            CASE
                WHEN n.published_at > NOW() - INTERVAL '3 hours' THEN 1
                WHEN n.published_at > NOW() - INTERVAL '24 hours' THEN 2
                WHEN n.published_at > NOW() - INTERVAL '7 days' THEN 3
                WHEN n.published_at > NOW() - INTERVAL '30 days' THEN 4
                ELSE 5
            END AS tier,
            CASE
                WHEN n.published_at > NOW() - INTERVAL '3 hours' THEN INTERVAL '10 minutes'
                WHEN n.published_at > NOW() - INTERVAL '24 hours' THEN INTERVAL '1 hour'
                WHEN n.published_at > NOW() - INTERVAL '7 days' THEN INTERVAL '6 hours'
                WHEN n.published_at > NOW() - INTERVAL '30 days' THEN INTERVAL '24 hours'
                ELSE INTERVAL '7 days'
            END AS recheck_interval
        FROM news n
        LEFT JOIN news_features nf ON n.unique_id = nf.unique_id
        WHERE n.published_at > NOW() - INTERVAL '5 months'
    )
    SELECT unique_id, url, image_url, published_at, integrity
    FROM candidates
    WHERE
        -- Nunca verificado OU último check mais antigo que o intervalo do tier
        integrity IS NULL
        OR (integrity ->> 'image_checked_at')::timestamptz < NOW() - recheck_interval
    ORDER BY
        tier ASC,
        CASE WHEN integrity IS NULL THEN 0 ELSE 1 END,
        COALESCE(
            (integrity ->> 'image_checked_at')::timestamptz,
            '1970-01-01'::timestamptz
        ) ASC
    LIMIT :batch_size
""")

# Proporção de artigos que devem ter check_content ativado (os mais recentes)
CONTENT_CHECK_RATIO = 0.25

# Allowlist de domínios aceitos pelo endpoint /verify/integrity do scraper.
# Espelha _ALLOWED_URL_PREFIXES em govbr_scraper/api.py.
ALLOWED_URL_PREFIXES = (
    "https://www.gov.br/",
    "https://agenciabrasil.ebc.com.br/",
    "https://imagens.ebc.com.br/",
    "https://memoria.ebc.com.br/",
    "https://tvbrasil.ebc.com.br/",
    "https://live.staticflickr.com/",
    "https://storage.googleapis.com/destaquesgovbr-thumbnails/",
)


def _is_allowed_url(url: str | None) -> bool:
    """Verifica se uma URL pertence à allowlist de domínios aceitos."""
    if not url:
        return True
    return any(url.startswith(prefix) for prefix in ALLOWED_URL_PREFIXES)


def fetch_priority_batch(db_url: str, batch_size: int = 400) -> list[dict]:
    """Busca artigos priorizados para verificação de integridade.

    Args:
        db_url: PostgreSQL connection string.
        batch_size: Número máximo de artigos no batch.

    Returns:
        Lista de dicts prontos para enviar ao endpoint /verify/integrity.
    """
    engine = create_engine(db_url, poolclass=NullPool)

    try:
        with engine.connect() as conn:
            rows = conn.execute(PRIORITY_QUERY, {"batch_size": batch_size}).fetchall()
    finally:
        engine.dispose()

    if not rows:
        logger.info("Nenhum artigo necessita verificação no momento")
        return []

    # Número de artigos com check de conteúdo
    content_check_count = max(1, int(len(rows) * CONTENT_CHECK_RATIO))

    articles = []
    filtered_count = 0
    for i, row in enumerate(rows):
        integrity = row.integrity or {}
        if isinstance(integrity, str):
            integrity = json.loads(integrity)

        image_url = row.image_url
        article_url = row.url

        if not _is_allowed_url(image_url):
            logger.warning(f"image_url filtrada (fora da allowlist): {image_url[:80]}")
            image_url = None
            filtered_count += 1

        if not _is_allowed_url(article_url):
            logger.warning(f"url filtrada (fora da allowlist): {article_url[:80]}")
            article_url = None

        article = {
            "unique_id": row.unique_id,
            "url": article_url,
            "image_url": image_url,
            "content_hash": integrity.get("content_hash"),
            "source_etag": integrity.get("source_etag"),
            "check_content": i < content_check_count,
        }
        articles.append(article)

    if filtered_count:
        logger.warning(
            f"{filtered_count}/{len(rows)} artigos com image_url filtrada por allowlist"
        )

    logger.info(
        f"Batch de verificação: {len(articles)} artigos "
        f"({content_check_count} com check de conteúdo)"
    )
    return articles
