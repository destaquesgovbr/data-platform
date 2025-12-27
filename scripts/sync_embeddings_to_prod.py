#!/usr/bin/env python3
"""
Sync embeddings from local PostgreSQL to production.

This script:
1. Starts Cloud SQL Proxy automatically
2. Reads embeddings from local PostgreSQL
3. Updates production PostgreSQL with the embeddings

Usage:
    poetry run python scripts/sync_embeddings_to_prod.py
    poetry run python scripts/sync_embeddings_to_prod.py --batch-size 500
    poetry run python scripts/sync_embeddings_to_prod.py --max-records 1000  # Test with limited records
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
from psycopg2.extras import execute_batch
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Cloud SQL configuration
CLOUD_SQL_INSTANCE = "inspire-7-finep:southamerica-east1:destaquesgovbr-postgres"
CLOUD_SQL_PROXY_PORT = 5434
CLOUD_SQL_DATABASE = "govbrnews"
CLOUD_SQL_USER = "govbrnews_app"
SECRET_PASSWORD = "govbrnews-postgres-password"

# Local database configuration
LOCAL_DATABASE_URL = os.getenv(
    "LOCAL_DATABASE_URL",
    "postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"
)


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


def count_embeddings(conn) -> int:
    """Count records with embeddings."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM news WHERE content_embedding IS NOT NULL")
        return cur.fetchone()[0]


def fetch_local_embeddings(conn, batch_size: int, offset: int, max_records: int = None):
    """Fetch embeddings from local database."""
    query = """
        SELECT unique_id, content_embedding, embedding_generated_at
        FROM news
        WHERE content_embedding IS NOT NULL
        ORDER BY embedding_generated_at DESC
        LIMIT %s OFFSET %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (batch_size, offset))
        return cur.fetchall()


def update_production_embeddings(conn, records: list) -> int:
    """Update production database with embeddings."""
    # Convert to format for execute_batch
    # records: [(unique_id, embedding, generated_at), ...]
    update_data = [
        (
            record[1],  # embedding (already a list from pgvector)
            record[2],  # generated_at
            record[0],  # unique_id
        )
        for record in records
    ]

    with conn.cursor() as cur:
        execute_batch(
            cur,
            """
                UPDATE news
                SET content_embedding = %s::vector,
                    embedding_generated_at = %s
                WHERE unique_id = %s
            """,
            update_data,
            page_size=100
        )

    conn.commit()
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Sync embeddings from local to production")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for sync")
    parser.add_argument("--max-records", type=int, default=None, help="Max records to sync (for testing)")
    args = parser.parse_args()

    print("=" * 60)
    print("🔄 Sync Embeddings: Local → Production")
    print("=" * 60)

    # Connect to local database
    print("\n🔌 Connecting to local database...")
    try:
        local_conn = get_connection(LOCAL_DATABASE_URL)
        print("   ✓ Connected to local")
    except Exception as e:
        print(f"   ✗ Failed to connect to local: {e}")
        sys.exit(1)

    # Check local embeddings
    local_count = count_embeddings(local_conn)
    print(f"   📊 Local embeddings: {local_count:,}")

    if local_count == 0:
        print("\n❌ No embeddings found in local database")
        sys.exit(1)

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
        prod_conn = get_connection(prod_url)
        print("   ✓ Connected to production")
    except Exception as e:
        print(f"   ✗ Failed to connect to production: {e}")
        sys.exit(1)

    # Check if production has embedding columns
    if not check_column_exists(prod_conn, "news", "content_embedding"):
        print("\n❌ Production database doesn't have embedding columns!")
        print("   Run: poetry run python scripts/apply_prod_migrations.py")
        sys.exit(1)

    # Check production embeddings before sync
    prod_count_before = count_embeddings(prod_conn)
    print(f"   📊 Production embeddings (before): {prod_count_before:,}")

    # Determine total records to sync
    total_to_sync = min(local_count, args.max_records) if args.max_records else local_count
    print(f"\n📤 Syncing {total_to_sync:,} embeddings to production...")

    # Sync in batches
    synced = 0
    offset = 0
    batch_size = args.batch_size

    with tqdm(total=total_to_sync, desc="   Syncing") as pbar:
        while synced < total_to_sync:
            # Fetch from local
            records = fetch_local_embeddings(
                local_conn,
                min(batch_size, total_to_sync - synced),
                offset
            )

            if not records:
                break

            # Update production
            try:
                updated = update_production_embeddings(prod_conn, records)
                synced += updated
                offset += len(records)
                pbar.update(updated)
            except Exception as e:
                print(f"\n   ✗ Error syncing batch: {e}")
                prod_conn.rollback()
                break

    # Check production embeddings after sync
    prod_count_after = count_embeddings(prod_conn)

    print("\n" + "=" * 60)
    print("✅ Sync completed!")
    print("=" * 60)
    print(f"   Records synced: {synced:,}")
    print(f"   Production embeddings (before): {prod_count_before:,}")
    print(f"   Production embeddings (after): {prod_count_after:,}")
    print(f"   New embeddings added: {prod_count_after - prod_count_before:,}")
    print("=" * 60)

    local_conn.close()
    prod_conn.close()


if __name__ == "__main__":
    main()
