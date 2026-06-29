#!/usr/bin/env python3
"""
Backfill de features básicas (readability_flesch, word_count, etc.) para uma janela.

Processa artigos sem readability_flesch em news_features.
Idempotente: faz UPSERT merge via || no JSONB existente.

Uso:
    DATABASE_URL=... .venv/bin/python scripts/backfill_features_window.py \\
        --date-from 2026-06-01 --date-to 2026-07-01 --limit 50000
"""
import argparse
import os
import sys
import time

import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data_platform.workers.feature_worker.features import compute_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date-from", default="2026-06-01")
    ap.add_argument("--date-to", default="2026-07-01")
    ap.add_argument("--limit", type=int, default=50000)
    args = ap.parse_args()

    db = os.environ.get("DATABASE_URL")
    if not db:
        print("ERRO: DATABASE_URL não definida", file=sys.stderr)
        return 1

    conn = psycopg2.connect(db)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT n.unique_id, n.content, n.image_url, n.video_url, n.published_at
        FROM news n
        LEFT JOIN news_features nf ON nf.unique_id = n.unique_id
        WHERE n.published_at >= %s::timestamptz
          AND n.published_at <  %s::timestamptz
          AND (nf.unique_id IS NULL OR NOT nf.features ? 'readability_flesch')
        ORDER BY n.published_at DESC
        LIMIT %s
        """,
        (args.date_from, args.date_to, args.limit),
    )
    rows = cur.fetchall()
    print(f"artigos para backfill: {len(rows)}")

    t0 = time.time()
    updated = skipped = 0
    for i, (uid, content, image_url, video_url, published_at) in enumerate(rows, 1):
        article = {
            "content": content,
            "image_url": image_url,
            "video_url": video_url,
            "published_at": published_at,
        }
        features = compute_all(article)
        if not features:
            skipped += 1
            continue
        cur.execute(
            """
            INSERT INTO news_features (unique_id, features, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (unique_id) DO UPDATE SET
              features   = news_features.features || EXCLUDED.features,
              updated_at = NOW()
            """,
            (uid, Json(features)),
        )
        updated += 1

        if i % 500 == 0:
            conn.commit()
            elapsed = time.time() - t0
            print(f"  {i}/{len(rows)}  updated={updated} skipped={skipped}  ({elapsed:.0f}s, {i/elapsed:.0f} art/s)")

    conn.commit()
    elapsed = time.time() - t0
    print(f"FIM: updated={updated} skipped={skipped} total={len(rows)}  {elapsed:.0f}s")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
