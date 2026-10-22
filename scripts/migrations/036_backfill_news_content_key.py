"""
Backfill de news.content_key (chave de quase-duplicata H5) para o corpus inteiro (DP-1b).

Percorre news em blocos cronológicos de CHUNK_DAYS dias chamando compute_content_keys — o mesmo
código da task da DAG project_entity_graph, que depois mantém só os últimos 10 dias. Cada bloco
lê 8 dias antes como contexto (semeado pela chave que o bloco anterior gravou) e 8 depois como
lookahead; grava só as linhas cuja chave muda (UPDATE ... IS DISTINCT FROM) e comita por bloco.
Intervalos sem artigo (ex.: 1970–2000) são pulados.

Idempotente e retomável: uma nova execução recalcula tudo e só grava o que mudou desde então.
Rodar com a DAG em paralelo é seguro (as duas chegam à mesma chave), mas é trabalho repetido.

Dry-run: calcula sem gravar só os últimos SAMPLE_DAYS dias e projeta o tempo (leitura + cálculo
+ ida e volta do banco) e as mudanças para o corpus, linear no número de artigos.

Custo (medido na amostra do relatório): ~1 ms de CPU por artigo, mais a leitura do conteúdo;
~360 mil artigos ≈ 6–10 min. Grava só os artigos em grupos (~10%): artigo sem quase-duplicata
fica NULL e cai no content_hash. Cada UPDATE dispara o trigger updated_at de news.

Rollback: content_key = NULL em lotes (o grafo e a graphql-api voltam ao content_hash).

Rodar separado da 035. Atenção: `migrate.py migrate --target 035` aplica TODAS as pendentes até a
035, não só ela (a 033, backfill do Flesch pt-BR, e a 034, tema 26, se ainda pendentes). Rodar
`status` antes e aplicar a 035 só com a 033/034 já aplicadas nas janelas delas.
"""

import os
import sys
import time
from datetime import datetime, timedelta

from loguru import logger

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from data_platform.jobs.graph.content_keys import compute_content_keys  # noqa: E402

CHUNK_DAYS = 90
SAMPLE_DAYS = 30
ROLLBACK_BATCH_SIZE = 2000

HAS_COLUMN_SQL = """
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'news' AND column_name = 'content_key'
    )
"""
CORPUS_SQL = "SELECT COUNT(*), MIN(published_at), MAX(published_at) FROM news"
NEXT_START_SQL = "SELECT MIN(published_at) FROM news WHERE published_at >= %(after)s"
COUNT_WITH_KEY_SQL = "SELECT COUNT(*) FROM news WHERE content_key IS NOT NULL"
ROLLBACK_BATCH_SQL = """
    UPDATE news SET content_key = NULL
    WHERE unique_id IN (
        SELECT unique_id FROM news
        WHERE content_key IS NOT NULL
        LIMIT %(limit)s
    )
"""


def chunk_end(since: datetime, last: datetime, days: int) -> datetime | None:
    """Fim (exclusivo) do bloco que começa em `since`; None no último (lê até o fim)."""
    until = since + timedelta(days=days)
    return until if until <= last else None


def project(sample_value: float, sample_size: int, total: int) -> float:
    """Projeção linear de um valor medido numa amostra para o corpus."""
    if sample_size == 0:
        return 0.0
    return sample_value / sample_size * total


def describe() -> str:
    return "Backfill de news.content_key (chave de quase-duplicata H5) para o corpus inteiro"


def _dry_run(conn, total: int, last: datetime) -> dict:
    since = last - timedelta(days=SAMPLE_DAYS)
    t0 = time.perf_counter()
    sample = compute_content_keys(conn, since=since, dry_run=True)
    seconds = time.perf_counter() - t0
    preview = {
        "preview": True,
        "total_articles": total,
        "sample_since": since.isoformat(),
        "sample_read": sample["read"],
        "sample_target": sample["target"],
        "sample_grouped": sample["grouped_target"],
        "sample_changes": sample["changes"],
        "sample_seconds": round(seconds, 2),
        "projected_changes": round(project(sample["changes"], sample["target"], total)),
        "projected_seconds": round(project(seconds, sample["read"], total), 1),
    }
    # O runner descarta o histórico do dry-run (rollback): o log é onde a projeção fica.
    logger.info("036 dry-run: " + " ".join(f"{k}={v}" for k, v in preview.items()))
    return preview


def migrate(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()
    try:
        cursor.execute(HAS_COLUMN_SQL)
        if not cursor.fetchone()[0]:
            # `migrate --dry-run` com 035 e 036 pendentes: o runner já desfez o preview da 035
            message = (
                "news.content_key ausente: aplicar a 035 antes "
                "(ver `status`: --target 035 inclui as pendentes anteriores)"
            )
            if dry_run:
                return {"preview": True, "message": message}
            raise RuntimeError(message)

        cursor.execute(CORPUS_SQL)
        total, first, last = cursor.fetchone()
        if total == 0:
            return {"rows_updated": 0, "message": "news vazia"}

        if dry_run:
            return _dry_run(conn, total, last)

        t0 = time.time()
        totals = {"chunks": 0, "target": 0, "grouped": 0, "changes": 0, "rows_updated": 0}
        since = first
        while since is not None:
            until = chunk_end(since, last, CHUNK_DAYS)
            result = compute_content_keys(conn, since=since, until=until)
            conn.commit()

            totals["chunks"] += 1
            totals["target"] += result["target"]
            totals["grouped"] += result["grouped_target"]
            totals["changes"] += result["changes"]
            totals["rows_updated"] += result["updated"]
            span = f"{since:%Y-%m-%d}..{until:%Y-%m-%d}" if until else f"{since:%Y-%m-%d}..fim"
            logger.info(
                f"036: bloco {span}: {totals['target']}/{total} artigos, "
                f"{totals['grouped']} em grupos, {totals['rows_updated']} gravados "
                f"({time.time() - t0:.0f}s)"
            )
            if until is None:
                break
            # próximo bloco começa no próximo artigo: pula intervalos vazios
            cursor.execute(NEXT_START_SQL, {"after": until})
            since = cursor.fetchone()[0]

        return {**totals, "elapsed_seconds": round(time.time() - t0, 2)}
    finally:
        cursor.close()


def rollback(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()
    try:
        cursor.execute(COUNT_WITH_KEY_SQL)
        to_clear = cursor.fetchone()[0]

        if dry_run:
            return {"rows_cleared": 0, "to_clear": to_clear, "preview": True}

        cleared = 0
        while True:
            cursor.execute(ROLLBACK_BATCH_SQL, {"limit": ROLLBACK_BATCH_SIZE})
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
    parser.add_argument("--dry-run", action="store_true", help="Amostra e projeta, sem gravar")
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
