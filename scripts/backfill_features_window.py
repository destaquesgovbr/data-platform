#!/usr/bin/env python3
"""
Backfill de features locais e content_annotations para uma janela de publicação.

Seleciona os artigos da janela sem linha em news_features, sem readability_flesch
ou sem content_annotations, e reprocessa cada um com o mesmo handler do
feature-worker (handle_feature_computation, caminho Postgres): features locais
(word_count, readability_flesch, ...) mais content_annotations derivadas de
features.entities, gravadas com merge || no JSONB (as demais chaves ficam).

Idempotente: depois de uma passada completa a seleção só traz artigos com menos
de 10 palavras, que nunca ganham readability_flesch (contados em sem_flesch).

Uso (sempre --dry-run, depois --limit 10, depois completo):
    DATABASE_URL=... .venv/bin/python scripts/backfill_features_window.py \\
        --date-from 2026-05-20 [--date-to AAAA-MM-DD] [--limit N] [--dry-run]

--date-to é exclusivo; o padrão é amanhã, para cobrir até hoje.
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data_platform.managers.postgres_manager import PostgresManager  # noqa: E402
from data_platform.workers.feature_worker.handler import handle_feature_computation  # noqa: E402

SELECT_SQL = """
    SELECT n.unique_id,
           COALESCE(nf.features ? 'readability_flesch', FALSE)  AS has_flesch,
           COALESCE(nf.features ? 'content_annotations', FALSE) AS has_annotations
    FROM news n
    LEFT JOIN news_features nf ON nf.unique_id = n.unique_id
    WHERE n.published_at >= %s
      AND n.published_at <  %s
      AND (nf.unique_id IS NULL
           OR NOT (nf.features ? 'readability_flesch' AND nf.features ? 'content_annotations'))
    ORDER BY n.published_at DESC
    LIMIT %s
"""

PROGRESS_EVERY = 500


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date-from", type=date.fromisoformat, default=date(2026, 6, 1))
    ap.add_argument(
        "--date-to",
        type=date.fromisoformat,
        default=date.today() + timedelta(days=1),
        help="exclusivo (padrão: amanhã)",
    )
    ap.add_argument("--limit", type=int, default=50000)
    ap.add_argument("--dry-run", action="store_true", help="só lista a seleção, sem gravar")
    args = ap.parse_args(argv)
    if args.date_from >= args.date_to:
        ap.error("--date-from deve ser anterior a --date-to")
    return args


def select_articles(
    db_url: str, date_from: date, date_to: date, limit: int
) -> list[tuple[str, bool, bool]]:
    """[(unique_id, has_flesch, has_annotations)] dos artigos a reprocessar."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(SELECT_SQL, (date_from, date_to, limit))
            return cur.fetchall()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    db = os.environ.get("DATABASE_URL")
    if not db:
        print("ERRO: DATABASE_URL não definida", file=sys.stderr)
        return 1

    rows = select_articles(db, args.date_from, args.date_to, args.limit)
    print(
        f"janela [{args.date_from}, {args.date_to}): {len(rows)} artigos selecionados "
        f"(sem readability_flesch: {sum(not f for _, f, _ in rows)}, "
        f"sem content_annotations: {sum(not a for _, _, a in rows)})"
    )
    if args.dry_run:
        for uid, _, _ in rows[:10]:
            print(f"  {uid}")
        print("dry-run: nada foi gravado")
        return 0

    pg = PostgresManager(connection_string=db, min_connections=1, max_connections=2)
    t0 = time.time()
    computed = not_found = failed = sem_flesch = 0
    try:
        for i, (uid, _, _) in enumerate(rows, 1):
            try:
                result = handle_feature_computation(uid, pg)
            except Exception as exc:
                failed += 1
                print(f"  ERRO {uid}: {exc}", file=sys.stderr)
                continue
            if result.get("status") != "computed":
                not_found += 1
                continue
            computed += 1
            if "readability_flesch" not in result.get("features", []):
                sem_flesch += 1
            if i % PROGRESS_EVERY == 0:
                elapsed = time.time() - t0
                print(f"  {i}/{len(rows)}  computed={computed} failed={failed}  ({elapsed:.0f}s)")
    finally:
        pg.close_all()

    print(
        f"FIM: computed={computed} sem_flesch={sem_flesch} not_found={not_found} "
        f"failed={failed} total={len(rows)}  {time.time() - t0:.0f}s"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
