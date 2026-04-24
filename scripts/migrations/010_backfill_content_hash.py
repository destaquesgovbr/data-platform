"""
Backfill content_hash for all existing news records.

Computes SHA-256(normalize(title) + "\\n" + normalize(content))[:16] for each row.
Runs in batches of 5000 to avoid long-running transactions. Idempotent.

Ref: destaquesgovbr/portal#108, destaquesgovbr/data-platform#138
"""

import hashlib
import re
import time
import unicodedata


BATCH_SIZE = 5000


# Canonical implementation: scraper/src/govbr_scraper/scrapers/content_hash.py
# Inlined here to avoid cross-repo dependency at migration time.
def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_content_hash(title: str, content: str | None) -> str | None:
    norm_title = normalize_text(title)
    norm_content = normalize_text(content)
    if not norm_title and not norm_content:
        return None
    normalized = norm_title + "\n" + norm_content
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def describe() -> str:
    return "Backfill content_hash para registros existentes na tabela news"


def migrate(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM news WHERE content_hash IS NULL")
    total_pending = cursor.fetchone()[0]

    if total_pending == 0:
        cursor.close()
        return {"rows_updated": 0, "message": "All rows already have content_hash"}

    if dry_run:
        cursor.close()
        return {"rows_updated": 0, "to_update": total_pending, "preview": True}

    t0 = time.time()
    total_updated = 0

    while True:
        cursor.execute(
            "SELECT id, title, content FROM news WHERE content_hash IS NULL LIMIT %s",
            (BATCH_SIZE,),
        )
        rows = cursor.fetchall()
        if not rows:
            break

        from psycopg2.extras import execute_batch

        params = []
        for row_id, title, content in rows:
            ch = compute_content_hash(title or "", content)
            params.append((ch, row_id))

        execute_batch(
            cursor,
            "UPDATE news SET content_hash = %s WHERE id = %s",
            params,
            page_size=1000,
        )
        total_updated += len(params)
        conn.commit()

    cursor.close()
    elapsed = time.time() - t0

    return {
        "rows_updated": total_updated,
        "elapsed_seconds": round(elapsed, 2),
    }


def rollback(conn, dry_run: bool = False) -> dict:
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM news WHERE content_hash IS NOT NULL")
    to_clear = cursor.fetchone()[0]

    if dry_run:
        cursor.close()
        return {"rows_cleared": 0, "to_clear": to_clear, "preview": True}

    cursor.execute("UPDATE news SET content_hash = NULL")
    cleared = cursor.rowcount
    cursor.close()

    return {"rows_cleared": cleared}
