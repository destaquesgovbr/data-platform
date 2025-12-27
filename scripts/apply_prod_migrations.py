#!/usr/bin/env python3
"""
Apply embedding migrations to production PostgreSQL.

This script:
1. Starts Cloud SQL Proxy automatically
2. Applies the pgvector extension and embedding columns
3. Creates the HNSW indexes for vector search

Usage:
    poetry run python scripts/apply_prod_migrations.py
    poetry run python scripts/apply_prod_migrations.py --dry-run  # Show SQL without executing
"""

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
from urllib.parse import quote_plus

import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Cloud SQL configuration
CLOUD_SQL_INSTANCE = "inspire-7-finep:southamerica-east1:destaquesgovbr-postgres"
CLOUD_SQL_PROXY_PORT = 5434
CLOUD_SQL_DATABASE = "govbrnews"
CLOUD_SQL_USER = "govbrnews_app"
SECRET_PASSWORD = "govbrnews-postgres-password"

# Migration SQL statements
MIGRATIONS = [
    {
        "name": "001_add_pgvector_extension",
        "description": "Enable pgvector extension",
        "sql": """
            CREATE EXTENSION IF NOT EXISTS vector;

            -- Verify extension is enabled
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                    RAISE EXCEPTION 'Failed to enable pgvector extension';
                END IF;
                RAISE NOTICE 'pgvector extension enabled successfully';
            END $$;
        """,
        "verify": "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
    },
    {
        "name": "002_add_embedding_columns",
        "description": "Add embedding columns to news table",
        "sql": """
            -- Add embedding column (768 dimensions for paraphrase-multilingual-mpnet-base-v2)
            ALTER TABLE news
            ADD COLUMN IF NOT EXISTS content_embedding vector(768);

            -- Add timestamp to track when embedding was generated
            ALTER TABLE news
            ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP WITH TIME ZONE;

            -- Add comments for documentation
            COMMENT ON COLUMN news.content_embedding IS
                'Semantic embedding (768-dim) from paraphrase-multilingual-mpnet-base-v2 model. Generated from title + summary (Phase 4.7)';

            COMMENT ON COLUMN news.embedding_generated_at IS
                'Timestamp when embedding was last generated (Phase 4.7)';
        """,
        "verify": """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'news'
              AND column_name IN ('content_embedding', 'embedding_generated_at')
            ORDER BY column_name;
        """
    },
    {
        "name": "003_create_embedding_indexes",
        "description": "Create HNSW indexes for vector search",
        "sql": """
            -- HNSW index for fast cosine similarity search
            CREATE INDEX IF NOT EXISTS idx_news_content_embedding_hnsw
            ON news USING hnsw (content_embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);

            -- Index for finding records without embeddings (for incremental generation)
            CREATE INDEX IF NOT EXISTS idx_news_embedding_status
            ON news (embedding_generated_at)
            WHERE content_embedding IS NULL;

            -- Index for incremental sync (recently updated embeddings)
            CREATE INDEX IF NOT EXISTS idx_news_embedding_updated
            ON news (embedding_generated_at DESC)
            WHERE content_embedding IS NOT NULL;
        """,
        "verify": """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'news'
              AND indexname LIKE '%embedding%'
            ORDER BY indexname;
        """
    }
]


def get_secret(secret_name: str) -> str:
    """Get a secret from GCP Secret Manager."""
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


def start_cloud_sql_proxy() -> subprocess.Popen:
    """Start Cloud SQL Proxy and return the process."""
    print(f"\n🌐 Starting Cloud SQL Proxy on port {CLOUD_SQL_PROXY_PORT}...")

    # Check if port is in use
    lsof = subprocess.run(
        ["lsof", "-ti", f":{CLOUD_SQL_PROXY_PORT}"],
        capture_output=True,
        text=True
    )
    if lsof.stdout.strip():
        print(f"   Port {CLOUD_SQL_PROXY_PORT} already in use, killing existing process...")
        subprocess.run(["kill", "-9", lsof.stdout.strip()], check=False)
        time.sleep(1)

    # Start proxy
    proxy = subprocess.Popen(
        [
            "cloud-sql-proxy",
            f"--port={CLOUD_SQL_PROXY_PORT}",
            CLOUD_SQL_INSTANCE
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(3)  # Wait for proxy to start

    if proxy.poll() is not None:
        raise RuntimeError("Cloud SQL Proxy failed to start")

    print(f"   ✓ Cloud SQL Proxy started (PID: {proxy.pid})")
    return proxy


def stop_cloud_sql_proxy(proxy: subprocess.Popen) -> None:
    """Stop Cloud SQL Proxy."""
    if proxy and proxy.poll() is None:
        print("\n🛑 Stopping Cloud SQL Proxy...")
        proxy.terminate()
        proxy.wait(timeout=5)


def get_connection(database_url: str):
    """Get a PostgreSQL connection."""
    return psycopg2.connect(database_url)


def check_column_exists(conn, table: str, column: str) -> bool:
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


def check_extension_exists(conn, extension: str) -> bool:
    """Check if an extension exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = %s)",
            (extension,)
        )
        return cur.fetchone()[0]


def apply_migration(conn, migration: dict, dry_run: bool = False) -> bool:
    """Apply a single migration."""
    name = migration["name"]
    description = migration["description"]
    sql = migration["sql"]
    verify = migration.get("verify")

    print(f"\n📋 {name}: {description}")

    if dry_run:
        print("   [DRY RUN] Would execute:")
        for line in sql.strip().split('\n'):
            if line.strip():
                print(f"   {line}")
        return True

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"   ✓ Migration applied successfully")

        # Run verification query if provided
        if verify:
            with conn.cursor() as cur:
                cur.execute(verify)
                results = cur.fetchall()
                if results:
                    print(f"   Verification: {results}")

        return True

    except Exception as e:
        conn.rollback()
        print(f"   ✗ Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Apply embedding migrations to production")
    parser.add_argument("--dry-run", action="store_true", help="Show SQL without executing")
    args = parser.parse_args()

    print("=" * 60)
    print("🔄 Apply Embedding Migrations to Production")
    print("=" * 60)

    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made")

    # Start Cloud SQL Proxy
    proxy = start_cloud_sql_proxy()
    atexit.register(stop_cloud_sql_proxy, proxy)

    # Handle signals for cleanup
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # Get production credentials
    print("\n🔑 Fetching production credentials...")
    prod_password = get_secret(SECRET_PASSWORD)
    print("   ✓ Got password from Secret Manager")

    # Build production URL
    escaped_password = quote_plus(prod_password)
    prod_url = f"postgresql://{CLOUD_SQL_USER}:{escaped_password}@localhost:{CLOUD_SQL_PROXY_PORT}/{CLOUD_SQL_DATABASE}"

    # Connect to production
    print("\n🔌 Connecting to production database...")
    try:
        conn = get_connection(prod_url)
        print("   ✓ Connected to production")
    except Exception as e:
        print(f"   ✗ Failed to connect: {e}")
        sys.exit(1)

    # Check current state
    print("\n📊 Current state:")
    has_vector = check_extension_exists(conn, "vector")
    has_embedding_col = check_column_exists(conn, "news", "content_embedding")
    print(f"   pgvector extension: {'✓ exists' if has_vector else '✗ missing'}")
    print(f"   content_embedding column: {'✓ exists' if has_embedding_col else '✗ missing'}")

    # Apply migrations
    print("\n" + "=" * 60)
    print("Applying migrations...")
    print("=" * 60)

    success_count = 0
    for migration in MIGRATIONS:
        if apply_migration(conn, migration, args.dry_run):
            success_count += 1

    # Final status
    print("\n" + "=" * 60)
    if args.dry_run:
        print(f"✅ Dry run complete: {success_count}/{len(MIGRATIONS)} migrations would be applied")
    else:
        print(f"✅ Migrations complete: {success_count}/{len(MIGRATIONS)} applied successfully")

        # Show final state
        print("\n📊 Final state:")
        has_vector = check_extension_exists(conn, "vector")
        has_embedding_col = check_column_exists(conn, "news", "content_embedding")
        print(f"   pgvector extension: {'✓ exists' if has_vector else '✗ missing'}")
        print(f"   content_embedding column: {'✓ exists' if has_embedding_col else '✗ missing'}")

    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
