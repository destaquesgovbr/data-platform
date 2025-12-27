#!/usr/bin/env python3
"""
Sync production PostgreSQL data to local development database.

This script copies agencies, themes, and news data from production Cloud SQL
to the local PostgreSQL container for development and testing purposes.

Features:
- Automatically starts Cloud SQL Proxy if not running
- Fetches credentials from Secret Manager
- Syncs agencies, themes, and news tables
- Supports date range filtering for news

Usage:
    # Sync December 2025 data (default):
    poetry run python scripts/sync_prod_to_local.py

    # Sync specific date range:
    poetry run python scripts/sync_prod_to_local.py --start-date 2025-01-01 --end-date 2025-12-31

    # Skip starting Cloud SQL Proxy (if already running):
    poetry run python scripts/sync_prod_to_local.py --no-proxy

Requirements:
    - gcloud CLI authenticated (gcloud auth login)
    - Cloud SQL Proxy installed (brew install cloud-sql-proxy)
    - Local PostgreSQL container running (docker-compose up -d postgres)

Environment Variables (optional):
    LOCAL_DATABASE_URL: Override local database URL
"""

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote_plus

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Cloud SQL configuration
CLOUD_SQL_INSTANCE = "inspire-7-finep:southamerica-east1:destaquesgovbr-postgres"
CLOUD_SQL_PROXY_PORT = 5434
CLOUD_SQL_DATABASE = "govbrnews"
CLOUD_SQL_USER = "govbrnews_app"

# Secret Manager secrets
SECRET_PASSWORD = "govbrnews-postgres-password"

# Global to track proxy process
_proxy_process = None


def get_secret(secret_id: str) -> str:
    """Fetch secret from Google Cloud Secret Manager."""
    try:
        result = subprocess.run(
            [
                "gcloud", "secrets", "versions", "access", "latest",
                "--secret", secret_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to fetch secret {secret_id}: {e.stderr}")
        sys.exit(1)


def is_proxy_running() -> bool:
    """Check if Cloud SQL Proxy is already running."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{CLOUD_SQL_PROXY_PORT}"],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def start_cloud_sql_proxy() -> subprocess.Popen | None:
    """Start Cloud SQL Proxy in the background."""
    global _proxy_process

    if is_proxy_running():
        print(f"   Cloud SQL Proxy already running on port {CLOUD_SQL_PROXY_PORT}")
        return None

    print(f"   Starting Cloud SQL Proxy on port {CLOUD_SQL_PROXY_PORT}...")

    try:
        _proxy_process = subprocess.Popen(
            [
                "cloud-sql-proxy",
                f"{CLOUD_SQL_INSTANCE}",
                f"--port={CLOUD_SQL_PROXY_PORT}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for proxy to be ready
        for i in range(10):
            time.sleep(1)
            if is_proxy_running():
                print(f"   ✓ Cloud SQL Proxy started (PID: {_proxy_process.pid})")
                return _proxy_process

        # Check if proxy failed
        if _proxy_process.poll() is not None:
            stderr = _proxy_process.stderr.read().decode() if _proxy_process.stderr else ""
            print(f"❌ Cloud SQL Proxy failed to start: {stderr}")
            sys.exit(1)

        print("❌ Cloud SQL Proxy did not start in time")
        sys.exit(1)

    except FileNotFoundError:
        print("❌ cloud-sql-proxy not found. Install with: brew install cloud-sql-proxy")
        sys.exit(1)


def stop_cloud_sql_proxy() -> None:
    """Stop Cloud SQL Proxy if we started it."""
    global _proxy_process
    if _proxy_process:
        print("\n🛑 Stopping Cloud SQL Proxy...")
        _proxy_process.terminate()
        _proxy_process.wait(timeout=5)
        _proxy_process = None


def get_connection(database_url: str) -> psycopg2.extensions.connection:
    """Create database connection from URL."""
    return psycopg2.connect(database_url)


def sync_agencies(
    prod_conn: psycopg2.extensions.connection,
    local_conn: psycopg2.extensions.connection,
) -> int:
    """Sync agencies table from production to local."""
    print("\n📁 Syncing agencies...")

    # Fetch from production
    with prod_conn.cursor() as cur:
        cur.execute("""
            SELECT id, key, name, type, parent_key, url, created_at
            FROM agencies
            ORDER BY id
        """)
        agencies = cur.fetchall()

    if not agencies:
        print("   No agencies found in production")
        return 0

    # Insert into local (upsert)
    with local_conn.cursor() as cur:
        # Temporarily disable FK constraint (agencies reference themselves)
        cur.execute("ALTER TABLE agencies DROP CONSTRAINT IF EXISTS fk_parent_agency")

        # Clear existing data
        cur.execute("TRUNCATE agencies CASCADE")

        # Insert all agencies
        execute_values(
            cur,
            """
            INSERT INTO agencies (id, key, name, type, parent_key, url, created_at)
            VALUES %s
            ON CONFLICT (key) DO UPDATE SET
                name = EXCLUDED.name,
                type = EXCLUDED.type,
                parent_key = EXCLUDED.parent_key,
                url = EXCLUDED.url
            """,
            agencies,
        )

        # Note: FK constraint not re-added because production has orphaned parent_keys
        # This is acceptable for local development

        # Reset sequence
        cur.execute("SELECT setval('agencies_id_seq', (SELECT MAX(id) FROM agencies))")

    local_conn.commit()
    print(f"   ✓ Synced {len(agencies)} agencies")
    return len(agencies)


def sync_themes(
    prod_conn: psycopg2.extensions.connection,
    local_conn: psycopg2.extensions.connection,
) -> int:
    """Sync themes table from production to local."""
    print("\n🏷️  Syncing themes...")

    # Fetch from production
    with prod_conn.cursor() as cur:
        cur.execute("""
            SELECT id, code, label, full_name, level, parent_code, created_at
            FROM themes
            ORDER BY level, id
        """)
        themes = cur.fetchall()

    if not themes:
        print("   No themes found in production")
        return 0

    # Insert into local
    with local_conn.cursor() as cur:
        # Temporarily disable FK constraint (themes reference themselves)
        cur.execute("ALTER TABLE themes DROP CONSTRAINT IF EXISTS fk_parent_theme")

        # Clear existing data
        cur.execute("TRUNCATE themes CASCADE")

        # Insert all themes
        execute_values(
            cur,
            """
            INSERT INTO themes (id, code, label, full_name, level, parent_code, created_at)
            VALUES %s
            ON CONFLICT (code) DO UPDATE SET
                label = EXCLUDED.label,
                full_name = EXCLUDED.full_name,
                level = EXCLUDED.level,
                parent_code = EXCLUDED.parent_code
            """,
            themes,
        )

        # Note: FK constraint not re-added for safety (same as agencies)

        # Reset sequence
        cur.execute("SELECT setval('themes_id_seq', (SELECT MAX(id) FROM themes))")

    local_conn.commit()
    print(f"   ✓ Synced {len(themes)} themes")
    return len(themes)


def check_column_exists(conn: psycopg2.extensions.connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
            )
            """,
            (table, column),
        )
        return cur.fetchone()[0]


def sync_news(
    prod_conn: psycopg2.extensions.connection,
    local_conn: psycopg2.extensions.connection,
    start_date: str,
    end_date: str,
    batch_size: int = 500,
) -> int:
    """Sync news table from production to local for date range."""
    print(f"\n📰 Syncing news from {start_date} to {end_date}...")

    # Check if production has embedding columns
    has_embeddings = check_column_exists(prod_conn, "news", "content_embedding")
    if has_embeddings:
        print("   Production has embedding columns")
    else:
        print("   Production does NOT have embedding columns yet")

    # Count records to sync
    with prod_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM news
            WHERE published_at >= %s AND published_at < %s::date + interval '1 day'
            """,
            (start_date, end_date),
        )
        total_count = cur.fetchone()[0]

    if total_count == 0:
        print("   No news found in date range")
        return 0

    print(f"   Found {total_count} news records to sync")

    # Delete existing news in date range (local)
    with local_conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM news
            WHERE published_at >= %s AND published_at < %s::date + interval '1 day'
            """,
            (start_date, end_date),
        )
        deleted = cur.rowcount
        if deleted > 0:
            print(f"   Deleted {deleted} existing local records in date range")
    local_conn.commit()

    # Build SELECT query based on available columns
    base_columns = [
        "unique_id", "agency_id", "theme_l1_id", "theme_l2_id", "theme_l3_id",
        "most_specific_theme_id", "title", "url", "image_url", "video_url",
        "category", "tags", "content", "editorial_lead", "subtitle", "summary",
        "published_at", "updated_datetime", "extracted_at", "created_at", "updated_at",
        "agency_key", "agency_name"
    ]

    if has_embeddings:
        select_columns = base_columns + ["content_embedding", "embedding_generated_at"]
        insert_columns = select_columns
    else:
        select_columns = base_columns
        insert_columns = base_columns

    select_query = f"""
        SELECT {', '.join(select_columns)}
        FROM news
        WHERE published_at >= %s AND published_at < %s::date + interval '1 day'
        ORDER BY published_at DESC
        LIMIT %s OFFSET %s
    """

    # Fetch and insert in batches
    synced = 0
    offset = 0

    with tqdm(total=total_count, desc="   Syncing news") as pbar:
        while offset < total_count:
            # Fetch batch from production
            with prod_conn.cursor() as cur:
                cur.execute(select_query, (start_date, end_date, batch_size, offset))
                news_batch = cur.fetchall()

            if not news_batch:
                break

            # Insert batch into local
            with local_conn.cursor() as cur:
                if has_embeddings:
                    insert_sql = f"""
                        INSERT INTO news ({', '.join(insert_columns)}) VALUES %s
                        ON CONFLICT (unique_id) DO UPDATE SET
                            summary = EXCLUDED.summary,
                            content_embedding = EXCLUDED.content_embedding,
                            embedding_generated_at = EXCLUDED.embedding_generated_at,
                            updated_at = NOW()
                    """
                else:
                    insert_sql = f"""
                        INSERT INTO news ({', '.join(insert_columns)}) VALUES %s
                        ON CONFLICT (unique_id) DO UPDATE SET
                            summary = EXCLUDED.summary,
                            updated_at = NOW()
                    """
                execute_values(cur, insert_sql, news_batch)
            local_conn.commit()

            synced += len(news_batch)
            offset += batch_size
            pbar.update(len(news_batch))

    # Reset sequence
    with local_conn.cursor() as cur:
        cur.execute("SELECT setval('news_id_seq', (SELECT COALESCE(MAX(id), 1) FROM news))")
    local_conn.commit()

    print(f"   ✓ Synced {synced} news records")
    return synced


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync production PostgreSQL data to local development database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-12-01",
        help="Start date for news sync (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2025-12-27",
        help="End date for news sync (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for news sync (default: 500)",
    )
    parser.add_argument(
        "--skip-agencies",
        action="store_true",
        help="Skip syncing agencies table",
    )
    parser.add_argument(
        "--skip-themes",
        action="store_true",
        help="Skip syncing themes table",
    )
    parser.add_argument(
        "--skip-news",
        action="store_true",
        help="Skip syncing news table",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Don't start Cloud SQL Proxy (assumes already running on port 5434)",
    )
    parser.add_argument(
        "--local-url",
        type=str,
        default=os.getenv(
            "LOCAL_DATABASE_URL",
            "postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"
        ),
        help="Local database URL (default: local docker-compose PostgreSQL)",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("🔄 Production to Local PostgreSQL Sync")
    print("=" * 60)

    # Start Cloud SQL Proxy if needed
    print("\n🌐 Setting up Cloud SQL connection...")
    if not args.no_proxy:
        start_cloud_sql_proxy()
        # Register cleanup on exit
        atexit.register(stop_cloud_sql_proxy)
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # Get production credentials
    print("\n🔑 Fetching production credentials...")
    prod_password = get_secret(SECRET_PASSWORD)
    print("   ✓ Got password from Secret Manager")

    # Build production URL (escape password for special characters)
    escaped_password = quote_plus(prod_password)
    prod_url = f"postgresql://{CLOUD_SQL_USER}:{escaped_password}@localhost:{CLOUD_SQL_PROXY_PORT}/{CLOUD_SQL_DATABASE}"

    # Connect to databases
    print("\n🔌 Connecting to databases...")
    try:
        prod_conn = get_connection(prod_url)
        print("   ✓ Connected to production (via Cloud SQL Proxy)")
    except Exception as e:
        print(f"❌ Failed to connect to production: {e}")
        sys.exit(1)

    try:
        local_conn = get_connection(args.local_url)
        print("   ✓ Connected to local")
    except Exception as e:
        print(f"❌ Failed to connect to local: {e}")
        print("\n   Make sure docker-compose is running:")
        print("   docker-compose up -d postgres")
        sys.exit(1)

    # Sync data
    print("\n" + "=" * 60)
    print("Starting sync from production to local")
    print("=" * 60)

    stats = {
        "agencies": 0,
        "themes": 0,
        "news": 0,
    }

    try:
        if not args.skip_agencies:
            stats["agencies"] = sync_agencies(prod_conn, local_conn)

        if not args.skip_themes:
            stats["themes"] = sync_themes(prod_conn, local_conn)

        if not args.skip_news:
            stats["news"] = sync_news(
                prod_conn,
                local_conn,
                args.start_date,
                args.end_date,
                args.batch_size,
            )

        # Print summary
        print("\n" + "=" * 60)
        print("✅ Sync completed!")
        print("=" * 60)
        print(f"   Agencies: {stats['agencies']}")
        print(f"   Themes:   {stats['themes']}")
        print(f"   News:     {stats['news']}")

        # Show sample data
        print("\n📊 Sample data from local database:")
        with local_conn.cursor() as cur:
            cur.execute("""
                SELECT unique_id, title, published_at,
                       CASE WHEN summary IS NOT NULL THEN '✓' ELSE '✗' END as has_summary,
                       CASE WHEN content_embedding IS NOT NULL THEN '✓' ELSE '✗' END as has_embedding
                FROM news
                ORDER BY published_at DESC
                LIMIT 5
            """)
            rows = cur.fetchall()

            if rows:
                print("\n   Recent news:")
                for row in rows:
                    title = row[1][:50] if row[1] else "N/A"
                    date = row[2].strftime('%Y-%m-%d') if row[2] else "N/A"
                    print(f"   - {date} | {title}... | summary: {row[3]} | embedding: {row[4]}")

            # Show summary stats
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE summary IS NOT NULL) as with_summary,
                    COUNT(*) FILTER (WHERE content_embedding IS NOT NULL) as with_embedding
                FROM news
            """)
            totals = cur.fetchone()
            print(f"\n   Total: {totals[0]} | With summary: {totals[1]} | With embeddings: {totals[2]}")

    except Exception as e:
        print(f"\n❌ Sync failed: {e}")
        raise
    finally:
        prod_conn.close()
        local_conn.close()


if __name__ == "__main__":
    main()
