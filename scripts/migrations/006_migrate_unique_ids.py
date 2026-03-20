"""
Migrate ~300k unique_ids from MD5 hashes to readable slugs.

Python migration following the runner interface (describe/migrate/rollback).
Adapted from scripts/migrate_unique_ids.py (issue #43).

Canonical source for ID generation: scraper/src/govbr_scraper/scrapers/unique_id.py
"""

import hashlib
import re
import time
import unicodedata
from datetime import date


# =============================================================================
# ID Generation Functions (inline copy from scraper)
# =============================================================================


def slugify(text: str, max_length: int = 100) -> str:
    """Convert text to a URL-friendly slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) > max_length:
        truncated = text[:max_length]
        if "-" in truncated:
            truncated = truncated.rsplit("-", 1)[0]
        text = truncated
    return text


def generate_suffix(agency: str, published_at_value, title: str) -> str:
    """Generate a deterministic 6-char hex suffix from article attributes."""
    date_str = (
        published_at_value.isoformat()
        if isinstance(published_at_value, date)
        else str(published_at_value)
    )
    hash_input = f"{agency}_{date_str}_{title}".encode("utf-8")
    return hashlib.md5(hash_input).hexdigest()[:6]


def generate_readable_unique_id(agency: str, published_at_value, title: str) -> str:
    """Generate a readable unique ID in the format: {slug}_{suffix}."""
    slug = slugify(title)
    suffix = generate_suffix(agency, published_at_value, title)
    if slug:
        return f"{slug}_{suffix}"
    return f"sem-titulo_{suffix}"


def _generate_id_with_extended_suffix(agency, published_at, title, extra_chars):
    """Generate ID with a longer suffix to resolve collisions."""
    slug = slugify(title)
    date_str = (
        published_at.isoformat() if isinstance(published_at, date) else str(published_at)
    )
    hash_input = f"{agency}_{date_str}_{title}".encode("utf-8")
    suffix = hashlib.md5(hash_input).hexdigest()[: 6 + extra_chars]
    if slug:
        return f"{slug}_{suffix}"
    return f"sem-titulo_{suffix}"


# =============================================================================
# Database helpers
# =============================================================================


def _fetch_all_news(conn):
    """Fetch all news rows needed for migration."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT unique_id, agency_key, published_at, title, legacy_unique_id "
        "FROM news ORDER BY unique_id"
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _build_id_mapping(rows):
    """Build mapping {old_unique_id: new_unique_id} from news rows."""
    mapping = {}
    seen_new_ids = {}
    collision_count = 0

    for unique_id, agency_key, published_at, title, _legacy in rows:
        new_id = generate_readable_unique_id(agency_key, published_at, title)

        if unique_id == new_id:
            seen_new_ids[new_id] = unique_id
            continue

        if new_id in seen_new_ids:
            for extra in range(1, 27):
                new_id = _generate_id_with_extended_suffix(
                    agency_key, published_at, title, extra
                )
                if new_id not in seen_new_ids:
                    break
            if new_id in seen_new_ids:
                raise ValueError(
                    f"Failed to resolve collision after 26 attempts for '{unique_id}'"
                )
            collision_count += 1

        mapping[unique_id] = new_id
        seen_new_ids[new_id] = unique_id

    new_ids = list(mapping.values())
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("Mapping contains duplicate new_ids after resolution")

    return mapping, collision_count


def _has_news_features_table(conn):
    """Check if news_features table exists."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM information_schema.tables "
        "  WHERE table_schema = 'public' AND table_name = 'news_features'"
        ")"
    )
    exists = cursor.fetchone()[0]
    cursor.close()
    return exists


def _get_fk_constraint_name(conn):
    """Get the FK constraint name on news_features referencing news."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tc.constraint_name "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name "
        "WHERE tc.table_name = 'news_features' "
        "  AND tc.constraint_type = 'FOREIGN KEY' "
        "  AND kcu.column_name = 'unique_id'"
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else None


# =============================================================================
# Runner interface
# =============================================================================


def describe() -> str:
    """Human description for logs and audit."""
    return "Migrar ~300k unique_ids de MD5 para slug legivel (issue #43)"


def migrate(conn, dry_run: bool = False) -> dict:
    """Execute the migration. conn is psycopg2 without autocommit."""
    rows = _fetch_all_news(conn)
    mapping, collision_count = _build_id_mapping(rows)

    if not mapping:
        return {"rows_migrated": 0, "already_migrated": len(rows), "collisions": 0}

    if dry_run:
        return {
            "rows_migrated": 0,
            "to_migrate": len(mapping),
            "collisions": collision_count,
            "preview": True,
        }

    from psycopg2.extras import execute_batch

    cursor = conn.cursor()
    t0 = time.time()

    # Backfill legacy_unique_id
    cursor.execute(
        "UPDATE news SET legacy_unique_id = unique_id WHERE legacy_unique_id IS NULL"
    )
    backfilled = cursor.rowcount

    # Handle news_features FK
    has_features = _has_news_features_table(conn)
    fk_name = None
    if has_features:
        fk_name = _get_fk_constraint_name(conn)
        if fk_name:
            cursor.execute(f"ALTER TABLE news_features DROP CONSTRAINT {fk_name}")

    # Update news_features
    if has_features:
        params = [(new_id, old_id) for old_id, new_id in mapping.items()]
        execute_batch(
            cursor,
            "UPDATE news_features SET unique_id = %s WHERE unique_id = %s",
            params,
            page_size=1000,
        )

    # Update news
    params = [(new_id, old_id) for old_id, new_id in mapping.items()]
    execute_batch(
        cursor,
        "UPDATE news SET unique_id = %s WHERE unique_id = %s",
        params,
        page_size=1000,
    )

    # Re-add FK
    if has_features and fk_name:
        cursor.execute(
            f"ALTER TABLE news_features ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE"
        )

    cursor.close()
    elapsed = time.time() - t0

    return {
        "rows_migrated": len(mapping),
        "backfilled_legacy": backfilled,
        "collisions": collision_count,
        "elapsed_seconds": round(elapsed, 2),
    }


def rollback(conn, dry_run: bool = False) -> dict:
    """Revert migration: restore MD5 unique_ids from legacy_unique_id."""
    cursor = conn.cursor()

    # Check legacy_unique_id populated
    cursor.execute("SELECT COUNT(*) FROM news WHERE legacy_unique_id IS NULL")
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        cursor.close()
        raise ValueError(f"{null_count} rows have NULL legacy_unique_id. Cannot rollback.")

    cursor.execute("SELECT COUNT(*) FROM news WHERE unique_id != legacy_unique_id")
    to_rollback = cursor.fetchone()[0]

    if to_rollback == 0:
        cursor.close()
        return {"rows_rolled_back": 0, "message": "All records already have MD5 unique_ids"}

    if dry_run:
        cursor.close()
        return {"rows_rolled_back": 0, "to_rollback": to_rollback, "preview": True}

    # Handle FK
    has_features = _has_news_features_table(conn)
    fk_name = None
    if has_features:
        fk_name = _get_fk_constraint_name(conn)
        if fk_name:
            cursor.execute(f"ALTER TABLE news_features DROP CONSTRAINT {fk_name}")

    # Update news_features
    if has_features:
        cursor.execute(
            "UPDATE news_features nf SET unique_id = n.legacy_unique_id "
            "FROM news n WHERE nf.unique_id = n.unique_id "
            "AND n.unique_id != n.legacy_unique_id"
        )

    # Update news
    cursor.execute(
        "UPDATE news SET unique_id = legacy_unique_id "
        "WHERE unique_id != legacy_unique_id"
    )
    rolled_back = cursor.rowcount

    # Re-add FK
    if has_features and fk_name:
        cursor.execute(
            f"ALTER TABLE news_features ADD CONSTRAINT {fk_name} "
            f"FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE"
        )

    # Verify
    cursor.execute("SELECT COUNT(*) FROM news WHERE unique_id != legacy_unique_id")
    remaining = cursor.fetchone()[0]
    cursor.close()

    return {"rows_rolled_back": rolled_back, "remaining_mismatched": remaining}
