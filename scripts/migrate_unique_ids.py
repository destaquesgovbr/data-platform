#!/usr/bin/env python3
"""
Migrate news unique_ids from MD5 hashes to readable slugs.

Phase 4 of issue #43: https://github.com/destaquesgovbr/data-platform/issues/43

Usage:
    poetry run python scripts/migrate_unique_ids.py --db-url "postgresql://..." --dry-run
    poetry run python scripts/migrate_unique_ids.py --db-url "postgresql://..."
    poetry run python scripts/migrate_unique_ids.py --db-url "postgresql://..." --rollback
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import time
import unicodedata
from datetime import date


# =============================================================================
# ID Generation Functions (inline copy)
# Canonical source: scraper/src/govbr_scraper/scrapers/unique_id.py
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


# =============================================================================
# Database helpers
# =============================================================================


def fetch_all_news(conn):
    """Fetch all news rows needed for migration.

    Uses a server-side cursor to avoid loading all rows into client memory at once
    when building the result list. For ~300k rows this keeps peak memory manageable.

    Returns list of tuples: (unique_id, agency_key, published_at, title, legacy_unique_id)
    """
    cursor = conn.cursor(name="fetch_news_for_migration")
    cursor.itersize = 5000
    cursor.execute(
        "SELECT unique_id, agency_key, published_at, title, legacy_unique_id "
        "FROM news ORDER BY id"
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _generate_id_with_extended_suffix(agency, published_at, title, extra_chars):
    """Generate ID with a longer suffix to resolve collisions."""
    slug = slugify(title)
    date_str = (
        published_at.isoformat()
        if isinstance(published_at, date)
        else str(published_at)
    )
    hash_input = f"{agency}_{date_str}_{title}".encode("utf-8")
    suffix = hashlib.md5(hash_input).hexdigest()[: 6 + extra_chars]
    if slug:
        return f"{slug}_{suffix}"
    return f"sem-titulo_{suffix}"


def build_id_mapping(rows):
    """Build mapping {old_unique_id: new_unique_id} from news rows.

    Skips rows where old_id == new_id (already migrated).
    Resolves collisions by extending the suffix (7, 8, ... chars).
    """
    mapping = {}
    seen_new_ids = {}  # new_id -> old_id
    collision_count = 0
    for unique_id, agency_key, published_at, title, _legacy in rows:
        new_id = generate_readable_unique_id(agency_key, published_at, title)
        if new_id in seen_new_ids and seen_new_ids[new_id] != unique_id:
            # Collision: extend suffix until unique
            for extra in range(1, 27):  # up to 32 hex chars total
                new_id = _generate_id_with_extended_suffix(
                    agency_key, published_at, title, extra
                )
                if new_id not in seen_new_ids:
                    break
            collision_count += 1
            print(f"   Resolved collision for '{unique_id}' -> '{new_id}'")
        if unique_id != new_id:
            mapping[unique_id] = new_id
            seen_new_ids[new_id] = unique_id
        else:
            seen_new_ids[new_id] = unique_id
    if collision_count:
        print(f"   Resolved {collision_count} collisions by extending suffix")
    return mapping


def has_news_features_table(conn):
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


def get_fk_constraint_name(conn):
    """Get the FK constraint name on news_features referencing news.

    Returns constraint name string or None.
    """
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
# Actions
# =============================================================================


def dry_run(conn, output_path):
    """Generate CSV mapping without modifying the database."""
    print("=" * 60)
    print("🔍 Dry Run: generating ID mapping")
    print("=" * 60)

    rows = fetch_all_news(conn)
    print(f"   Found {len(rows)} news records")

    mapping = build_id_mapping(rows)
    print(f"   {len(mapping)} records need migration ({len(rows) - len(mapping)} already migrated)")

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["old_unique_id", "new_unique_id"])
        for old_id, new_id in mapping.items():
            writer.writerow([old_id, new_id])

    print(f"\n   ✓ CSV written to {output_path} ({len(mapping)} rows)")
    print("   ℹ️  No database changes were made")
    print("=" * 60)


def migrate(conn, batch_size=1000):
    """Migrate all unique_ids from MD5 to readable slugs."""
    print("=" * 60)
    print("🔄 Migrating unique_ids: MD5 → readable slugs")
    print("=" * 60)

    # 1. Fetch and build mapping
    rows = fetch_all_news(conn)
    print(f"   Found {len(rows)} news records")

    mapping = build_id_mapping(rows)
    if not mapping:
        print("   ℹ️  All records already migrated. Nothing to do.")
        return

    print(f"   {len(mapping)} records to migrate")

    cursor = conn.cursor()

    try:
        # 3. Backfill legacy_unique_id where NULL
        cursor.execute(
            "UPDATE news SET legacy_unique_id = unique_id WHERE legacy_unique_id IS NULL"
        )
        backfilled = cursor.rowcount
        print(f"   ✓ Backfilled legacy_unique_id for {backfilled} rows")

        # 4. Handle news_features FK
        has_features = has_news_features_table(conn)
        fk_name = None
        if has_features:
            fk_name = get_fk_constraint_name(conn)
            if fk_name:
                cursor.execute(
                    f"ALTER TABLE news_features DROP CONSTRAINT {fk_name}"
                )
                print(f"   ✓ Dropped FK constraint: {fk_name}")

        # 5. Update news_features in batches (execute_batch for performance)
        from psycopg2.extras import execute_batch

        if has_features:
            cursor.execute("SELECT COUNT(*) FROM news_features")
            features_before = cursor.fetchone()[0]

            params = [(new_id, old_id) for old_id, new_id in mapping.items()]
            execute_batch(
                cursor,
                "UPDATE news_features SET unique_id = %s WHERE unique_id = %s",
                params,
                page_size=batch_size,
            )
            print(f"   ✓ Updated news_features ({features_before} rows in table)")

        # 6. Update news in batches (execute_batch for performance)
        params = [(new_id, old_id) for old_id, new_id in mapping.items()]
        total = len(params)
        t0 = time.time()
        for i in range(0, total, batch_size):
            batch = params[i : i + batch_size]
            execute_batch(
                cursor,
                "UPDATE news SET unique_id = %s WHERE unique_id = %s",
                batch,
                page_size=batch_size,
            )
            elapsed = time.time() - t0
            print(f"   Processed {min(i + batch_size, total)}/{total} rows ({elapsed:.1f}s)...")
        print(f"   ✓ Updated {total} news rows")

        # 7. Re-add FK
        if has_features and fk_name:
            cursor.execute(
                f"ALTER TABLE news_features ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE"
            )
            print(f"   ✓ Re-added FK constraint: {fk_name}")

        # 8. Verify integrity
        cursor.execute(
            "SELECT COUNT(*) FROM news WHERE unique_id = legacy_unique_id"
        )
        unchanged = cursor.fetchone()[0]
        if unchanged > 0:
            print(f"\n⚠️  {unchanged} rows still have unique_id = legacy_unique_id")

        # 9. Commit
        conn.commit()
        print(f"\n✅ Migration complete: {total} news records migrated")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during migration: {e}")
        print("   Transaction rolled back. No changes were made.")
        raise
    finally:
        cursor.close()


def rollback(conn, batch_size=1000):
    """Rollback migration: restore MD5 unique_ids from legacy_unique_id."""
    print("=" * 60)
    print("⏪ Rolling back: restoring MD5 unique_ids")
    print("=" * 60)

    cursor = conn.cursor()

    try:
        # 1. Check legacy_unique_id is populated
        cursor.execute(
            "SELECT COUNT(*) FROM news WHERE legacy_unique_id IS NULL"
        )
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            print(f"❌ {null_count} rows have NULL legacy_unique_id. Cannot rollback.")
            sys.exit(1)

        # 2. Count rows to rollback
        cursor.execute(
            "SELECT COUNT(*) FROM news WHERE unique_id != legacy_unique_id"
        )
        to_rollback = cursor.fetchone()[0]
        if to_rollback == 0:
            print("   ℹ️  All records already have MD5 unique_ids. Nothing to rollback.")
            return

        print(f"   {to_rollback} records to rollback")

        # 3. Handle news_features FK
        has_features = has_news_features_table(conn)
        fk_name = None
        if has_features:
            fk_name = get_fk_constraint_name(conn)
            if fk_name:
                cursor.execute(
                    f"ALTER TABLE news_features DROP CONSTRAINT {fk_name}"
                )
                print(f"   ✓ Dropped FK constraint: {fk_name}")

        # 4. Update news_features to legacy IDs
        if has_features:
            cursor.execute(
                "UPDATE news_features nf SET unique_id = n.legacy_unique_id "
                "FROM news n WHERE nf.unique_id = n.unique_id "
                "AND n.unique_id != n.legacy_unique_id"
            )
            print(f"   ✓ Rolled back {cursor.rowcount} news_features rows")

        # 5. Update news to legacy IDs
        cursor.execute(
            "UPDATE news SET unique_id = legacy_unique_id "
            "WHERE unique_id != legacy_unique_id"
        )
        rolled_back = cursor.rowcount
        print(f"   ✓ Rolled back {rolled_back} news rows")

        # 6. Re-add FK
        if has_features and fk_name:
            cursor.execute(
                f"ALTER TABLE news_features ADD CONSTRAINT {fk_name} "
                f"FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE"
            )
            print(f"   ✓ Re-added FK constraint: {fk_name}")

        # 7. Verify
        cursor.execute(
            "SELECT COUNT(*) FROM news WHERE unique_id != legacy_unique_id"
        )
        remaining = cursor.fetchone()[0]
        if remaining > 0:
            print(f"\n⚠️  {remaining} rows still differ from legacy_unique_id")

        # 8. Commit
        conn.commit()
        print(f"\n✅ Rollback complete: {rolled_back} records restored")
        print("=" * 60)

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during rollback: {e}")
        print("   Transaction rolled back. No changes were made.")
        raise
    finally:
        cursor.close()


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Migrate news unique_ids from MD5 hashes to readable slugs."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection string (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate CSV mapping without modifying the database",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Restore MD5 unique_ids from legacy_unique_id column",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Number of records per batch (default: 1000)",
    )
    parser.add_argument(
        "--output",
        default="migration_mapping.csv",
        help="CSV output path for --dry-run (default: migration_mapping.csv)",
    )

    args = parser.parse_args()

    if not args.db_url:
        print("❌ No database URL. Use --db-url or set DATABASE_URL.")
        sys.exit(1)

    if args.dry_run and args.rollback:
        print("❌ Cannot use --dry-run and --rollback together.")
        sys.exit(1)

    import psycopg2

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False

    try:
        if args.dry_run:
            dry_run(conn, args.output)
        elif args.rollback:
            rollback(conn, args.batch_size)
        else:
            migrate(conn, args.batch_size)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
