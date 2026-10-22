"""
Backfill de readability_flesch_ptbr nas linhas existentes de news_features (DP-1).

Só UPDATE: pagina news_features por unique_id (keyset na PK, lotes de BATCH_SIZE, INNER
JOIN com news para ler o content). Para cada linha com content e sem a chave, calcula
compute_readability_flesch_ptbr (a mesma função do feature-worker) e grava o lote num
único UPDATE ... FROM (VALUES ...) com merge JSONB (||), via execute_values, com commit
por lote. As demais chaves da linha ficam.

Notícia sem linha em news_features não ganha linha nova: as ~153,8 mil notícias nessa
situação (quase todas anteriores a 2022) ficam de fora por decisão (somariam +75% de
linhas à tabela). Artigos novos recebem a chave do feature-worker.

Retomável: a seleção pula quem já tem a chave (do backfill ou do feature-worker já
deployado). Textos com menos de 10 palavras não ganham a chave (contados em too_short)
e voltam a ser lidos numa nova execução.

Dry-run: conta os pendentes e cronometra o cálculo numa amostra de SAMPLE_SIZE artigos
para projetar o tempo total (só CPU; leitura e escrita no banco não entram).

Rollback: remove a chave em lotes — inclusive a gravada pelo feature-worker; com o worker
ainda deployado, artigos novos voltam a recebê-la.

Cada UPDATE reescreve a linha inteira de news_features (TOAST + entradas do índice GIN):
conferir espaço em disco antes e acompanhar WAL/bloat (autovacuum) durante a execução.

Rodar separado da 032: `migrate.py migrate --target 032` aplica só a 032.
"""

import json
import math
import os
import sys
import time

from loguru import logger
from psycopg2.extras import execute_values

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from data_platform.workers.feature_worker.features import (  # noqa: E402
    compute_readability_flesch_ptbr,
)

FEATURE_KEY = "readability_flesch_ptbr"
BATCH_SIZE = 2000
SAMPLE_SIZE = 1000

# features é NOT NULL (migração 004): sem COALESCE.
_PENDING_FILTER = """
    FROM news_features nf
    JOIN news n ON n.unique_id = nf.unique_id
    WHERE n.content IS NOT NULL
      AND n.content <> ''
      AND NOT (nf.features ? %(key)s)
"""

COUNT_PENDING_SQL = "SELECT COUNT(*)" + _PENDING_FILTER

SELECT_PENDING_SQL = (
    "SELECT nf.unique_id, n.content"
    + _PENDING_FILTER
    + """
      AND nf.unique_id > %(after)s
    ORDER BY nf.unique_id
    LIMIT %(limit)s
"""
)

UPDATE_SQL = """
    UPDATE news_features AS nf
    SET features = nf.features || v.features
    FROM (VALUES %s) AS v (unique_id, features)
    WHERE nf.unique_id = v.unique_id
"""
UPDATE_TEMPLATE = "(%s, %s::jsonb)"

COUNT_WITH_KEY_SQL = "SELECT COUNT(*) FROM news_features WHERE features ? %(key)s"

ROLLBACK_BATCH_SQL = """
    UPDATE news_features SET features = features - %(key)s
    WHERE unique_id IN (
        SELECT unique_id FROM news_features
        WHERE features ? %(key)s
        LIMIT %(limit)s
    )
"""


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


def project_seconds(sample_seconds: float, sample_size: int, pending: int) -> float:
    """Tempo de cálculo projetado para os pendentes, linear na amostra cronometrada."""
    if sample_size == 0:
        return 0.0
    return sample_seconds / sample_size * pending


def describe() -> str:
    return (
        "Backfill de readability_flesch_ptbr (Flesch pt-BR, Martins/1996) nas linhas "
        "existentes de news_features (só UPDATE)"
    )


def migrate(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()
    try:
        cursor.execute(COUNT_PENDING_SQL, {"key": FEATURE_KEY})
        pending = cursor.fetchone()[0]

        if dry_run:
            cursor.execute(
                SELECT_PENDING_SQL, {"key": FEATURE_KEY, "after": "", "limit": SAMPLE_SIZE}
            )
            sample = cursor.fetchall()
            t0 = time.perf_counter()
            _, sample_too_short = build_batch(sample)
            sample_seconds = time.perf_counter() - t0
            preview = {
                "preview": True,
                "pending": pending,
                "batches": math.ceil(pending / BATCH_SIZE),
                "sample_size": len(sample),
                "sample_too_short": sample_too_short,
                "sample_compute_seconds": round(sample_seconds, 3),
                "projected_compute_seconds": round(
                    project_seconds(sample_seconds, len(sample), pending), 1
                ),
            }
            # O runner descarta o histórico do dry-run (rollback): o log é onde a projeção fica.
            logger.info("033 dry-run: " + " ".join(f"{k}={v}" for k, v in preview.items()))
            return preview

        if pending == 0:
            return {
                "rows_updated": 0,
                "message": f"Nenhuma linha de news_features pendente sem {FEATURE_KEY}",
            }

        t0 = time.time()
        after = ""
        scanned = updated = too_short = 0
        while True:
            cursor.execute(
                SELECT_PENDING_SQL, {"key": FEATURE_KEY, "after": after, "limit": BATCH_SIZE}
            )
            rows = cursor.fetchall()
            if not rows:
                break

            values, short = build_batch(rows)
            if values:
                execute_values(
                    cursor, UPDATE_SQL, values, template=UPDATE_TEMPLATE, page_size=BATCH_SIZE
                )
            conn.commit()

            after = rows[-1][0]
            scanned += len(rows)
            updated += len(values)
            too_short += short
            logger.info(
                f"033: {scanned}/{pending} lidos, {updated} gravados, {too_short} curtos "
                f"({time.time() - t0:.0f}s)"
            )

        return {
            "rows_updated": updated,
            "too_short": too_short,
            "scanned": scanned,
            "elapsed_seconds": round(time.time() - t0, 2),
        }
    finally:
        cursor.close()


def rollback(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()
    try:
        cursor.execute(COUNT_WITH_KEY_SQL, {"key": FEATURE_KEY})
        to_clear = cursor.fetchone()[0]

        if dry_run:
            return {"rows_cleared": 0, "to_clear": to_clear, "preview": True}

        cleared = 0
        while True:
            cursor.execute(ROLLBACK_BATCH_SQL, {"key": FEATURE_KEY, "limit": BATCH_SIZE})
            if cursor.rowcount == 0:
                break
            cleared += cursor.rowcount
            conn.commit()

        return {"rows_cleared": cleared}
    finally:
        cursor.close()


if __name__ == "__main__":
    import argparse

    import psycopg2

    parser = argparse.ArgumentParser(description=describe())
    parser.add_argument("--dry-run", action="store_true", help="Conta e projeta, sem gravar")
    parser.add_argument("--confirm", action="store_true", help="Executa o backfill")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("Must specify --dry-run or --confirm")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        result = migrate(conn, dry_run=args.dry_run)
        print(result)
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        conn.close()
