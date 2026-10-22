"""Cobertura contínua do Flesch pt-BR em news_features (DP-1c).

A migração 033 preencheu readability_flesch_ptbr nas linhas que existiam em news_features, e o
feature-worker grava a chave em todo artigo que processa. Outros escritores (enrichment_backfill,
ner-backfill) criam ou reescrevem linhas sem passar pelo worker e ficam sem a chave. A task
diária fill_flesch_ptbr (DAG aggregate_engagement) relê as linhas tocadas nos últimos
LOOKBACK_DAYS dias (índice em updated_at) que têm content e não têm a chave, calcula com a mesma
função do worker e grava com merge no JSONB (||), em lotes com commit, como a 033.

- Textos com menos de 10 palavras não ganham a chave (too_short) e voltam a ser lidos enquanto a
  linha estiver na janela: é barato e os mantém visíveis no resultado.
- O UPDATE só grava se a chave ainda faltar: não regrava o que o worker escreveu entre o SELECT e
  o UPDATE.
- `lookback_days=None` varre a tabela inteira (disparo manual com
  `--conf '{"flesch_lookback_days": null}'`). RUN_LIMIT limita as linhas lidas por execução.

Só psycopg2 e pyphen (via readability_ptbr): roda no Composer como plugin.
"""

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg2.extras import execute_values

from data_platform.jobs.features.readability_ptbr import compute_readability_flesch_ptbr

logger = logging.getLogger(__name__)

FEATURE_KEY = "readability_flesch_ptbr"
LOOKBACK_DAYS = 3
RUN_LIMIT = 50000
BATCH_SIZE = 1000

# features é NOT NULL (migração 004): sem COALESCE. Mesmo filtro da 033, mais a janela.
_SELECT_PENDING_SQL = """
    SELECT nf.unique_id, n.content
    FROM news_features nf
    JOIN news n ON n.unique_id = nf.unique_id
    WHERE {window}n.content IS NOT NULL
      AND n.content <> ''
      AND NOT (nf.features ? %(key)s)
      AND nf.unique_id > %(after)s
    ORDER BY nf.unique_id
    LIMIT %(limit)s
"""

# execute_values só aceita o %s do VALUES: a chave da guarda vai literal.
UPDATE_SQL = f"""
    UPDATE news_features AS nf
    SET features = nf.features || v.features
    FROM (VALUES %s) AS v (unique_id, features)
    WHERE nf.unique_id = v.unique_id
      AND NOT (nf.features ? '{FEATURE_KEY}')
"""
UPDATE_TEMPLATE = "(%s, %s::jsonb)"


def build_select_pending(since: datetime | None) -> str:
    """SELECT dos pendentes em ordem de unique_id (keyset); `since=None` sem janela."""
    window = "nf.updated_at >= %(since)s\n      AND " if since is not None else ""
    return _SELECT_PENDING_SQL.format(window=window)


def build_batch(rows: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], int]:
    """[(unique_id, content)] -> ([(unique_id, features_json)], nº de textos curtos)."""
    values = []
    too_short = 0
    for unique_id, content in rows:
        flesch = compute_readability_flesch_ptbr(content)
        if flesch is None:
            too_short += 1
            continue
        values.append((unique_id, json.dumps({FEATURE_KEY: flesch})))
    return values, too_short


def fill_missing_flesch_ptbr(
    conn: Any,
    since: datetime | None,
    limit: int = RUN_LIMIT,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Preenche a chave nas linhas pendentes, com commit por lote (dry-run: só calcula)."""
    t0 = time.perf_counter()
    sql = build_select_pending(since)
    after = ""
    scanned = updated = would_update = too_short = 0
    exhausted = False
    cursor = conn.cursor()
    try:
        while scanned < limit:
            page = min(batch_size, limit - scanned)
            cursor.execute(sql, {"key": FEATURE_KEY, "since": since, "after": after, "limit": page})
            rows = cursor.fetchall()
            if not rows:
                exhausted = True
                break

            values, short = build_batch(rows)
            scanned += len(rows)
            too_short += short
            after = rows[-1][0]
            if values and not dry_run:
                execute_values(
                    cursor, UPDATE_SQL, values, template=UPDATE_TEMPLATE, page_size=len(values)
                )
                updated += cursor.rowcount
                conn.commit()
            elif values:
                would_update += len(values)

            if len(rows) < page:
                exhausted = True
                break
    finally:
        cursor.close()

    result: dict[str, Any] = {
        "scanned": scanned,
        "updated": updated,
        "would_update": would_update,
        "too_short": too_short,
        "exhausted": exhausted,
        "since": since.isoformat() if since else None,
        "limit": limit,
        "dry_run": dry_run,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }
    logger.info("fill_flesch_ptbr: %s", result)
    return result


def run_fill_flesch_ptbr(
    db_url: str,
    lookback_days: int | None = LOOKBACK_DAYS,
    limit: int = RUN_LIMIT,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tarefa da DAG: janela de `lookback_days` dias por updated_at (None = tabela inteira)."""
    import psycopg2

    since = None
    if lookback_days is not None:
        since = (now or datetime.now(UTC)) - timedelta(days=lookback_days)
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        return fill_missing_flesch_ptbr(conn, since=since, limit=limit, dry_run=dry_run)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
