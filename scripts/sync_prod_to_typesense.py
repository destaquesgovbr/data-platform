#!/usr/bin/env python3
"""
Sync embeddings from production PostgreSQL to production Typesense.

This script:
1. Starts Cloud SQL Proxy automatically
2. Connects to production PostgreSQL
3. Syncs embeddings to production Typesense

Usage:
    poetry run python scripts/sync_prod_to_typesense.py
    poetry run python scripts/sync_prod_to_typesense.py --start-date 2025-01-01 --end-date 2025-12-31
    poetry run python scripts/sync_prod_to_typesense.py --full-sync  # Sync all, ignore last sync timestamp
    poetry run python scripts/sync_prod_to_typesense.py --max-records 1000  # Test with limited records
"""

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import psycopg2
import typesense
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

# Typesense configuration (from GCP secrets)
TYPESENSE_WRITE_SECRET = "typesense-write-conn"

# Collection configuration
COLLECTION_NAME = "news"
BATCH_SIZE = 500


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


def get_pg_connection(database_url: str):
    """Get a PostgreSQL connection."""
    return psycopg2.connect(database_url)


def get_typesense_client(config: Dict) -> typesense.Client:
    """Get a Typesense client from config dict."""
    return typesense.Client({
        'nodes': [{
            'host': config['host'],
            'port': str(config['port']),
            'protocol': config.get('protocol', 'http')
        }],
        'api_key': config['apiKey'],
        'connection_timeout_seconds': 10
    })


def check_typesense_collection(client: typesense.Client) -> Dict:
    """Check if the Typesense collection exists and has embedding field."""
    try:
        collection = client.collections[COLLECTION_NAME].retrieve()
        print(f"   ✓ Collection '{COLLECTION_NAME}' found with {collection['num_documents']} documents")

        # Check if content_embedding field exists
        embedding_field = next(
            (f for f in collection['fields'] if f['name'] == 'content_embedding'),
            None
        )

        if not embedding_field:
            print(f"   ⚠ Collection doesn't have 'content_embedding' field")
            print("   You may need to recreate the collection with the updated schema")
        else:
            print(f"   ✓ content_embedding field exists (dims: {embedding_field.get('num_dim', 'unknown')})")

        return collection

    except typesense.exceptions.ObjectNotFound:
        raise ValueError(
            f"Collection '{COLLECTION_NAME}' not found in Typesense. "
            "Create it first with the schema that includes content_embedding field."
        )


def count_embeddings_in_pg(conn, start_date: str, end_date: str) -> int:
    """Count records with embeddings in PostgreSQL."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM news
            WHERE published_at >= %s
              AND published_at < %s::date + INTERVAL '1 day'
              AND content_embedding IS NOT NULL
            """,
            (start_date, end_date)
        )
        return cur.fetchone()[0]


def fetch_news_with_embeddings(
    conn,
    start_date: str,
    end_date: str,
    batch_size: int,
    offset: int
) -> List[Dict]:
    """Fetch news records with embeddings from PostgreSQL."""
    query = """
        SELECT
            n.unique_id,
            n.agency_key,
            n.agency_name,
            n.title,
            n.url,
            n.image_url,
            n.category,
            n.content,
            n.summary,
            n.subtitle,
            n.editorial_lead,
            n.published_at,
            n.extracted_at,
            t1.code as theme_l1_code,
            t1.label as theme_l1_label,
            t2.code as theme_l2_code,
            t2.label as theme_l2_label,
            t3.code as theme_l3_code,
            t3.label as theme_l3_label,
            tm.code as most_specific_theme_code,
            tm.label as most_specific_theme_label,
            n.content_embedding,
            n.embedding_generated_at
        FROM news n
        LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
        LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
        LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
        LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
        WHERE n.published_at >= %s
          AND n.published_at < %s::date + INTERVAL '1 day'
          AND n.content_embedding IS NOT NULL
        ORDER BY n.published_at DESC
        LIMIT %s OFFSET %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (start_date, end_date, batch_size, offset))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def prepare_typesense_document(news: Dict) -> Dict:
    """Prepare a news record for Typesense indexing."""
    doc = {
        'id': news['unique_id'],
        'unique_id': news['unique_id'],
        'published_at': int(news['published_at'].timestamp()) if news['published_at'] else 0
    }

    # Add optional fields
    optional_fields = [
        'agency_key', 'title', 'url', 'image_url', 'category',
        'content', 'summary', 'subtitle', 'editorial_lead',
        'theme_l1_code', 'theme_l1_label',
        'theme_l2_code', 'theme_l2_label',
        'theme_l3_code', 'theme_l3_label',
        'most_specific_theme_code', 'most_specific_theme_label'
    ]

    for field in optional_fields:
        if news.get(field):
            doc[field] = str(news[field]).strip()

    # Add agency_name as agency (for compatibility)
    if news.get('agency_name'):
        doc['agency'] = news['agency_name']

    # Add extracted_at timestamp
    if news.get('extracted_at'):
        doc['extracted_at'] = int(news['extracted_at'].timestamp())

    # Add published_year and published_month for faceting
    if news.get('published_at'):
        doc['published_year'] = news['published_at'].year
        doc['published_month'] = news['published_at'].month

    # Add content_embedding
    if news.get('content_embedding'):
        embedding = news['content_embedding']

        if isinstance(embedding, str):
            # Parse string representation
            embedding_list = json.loads(embedding)
        elif isinstance(embedding, list):
            # Already a list
            embedding_list = embedding
        else:
            # Unknown format, skip
            embedding_list = None

        if embedding_list:
            doc['content_embedding'] = embedding_list

    return doc


def upsert_documents_batch(client: typesense.Client, documents: List[Dict]) -> int:
    """Upsert a batch of documents to Typesense."""
    try:
        results = client.collections[COLLECTION_NAME].documents.import_(
            documents,
            {'action': 'upsert'}
        )

        successes = sum(1 for r in results if r.get('success'))
        failures = len(results) - successes

        if failures > 0:
            # Log first few failures
            for r in results[:3]:
                if not r.get('success'):
                    print(f"      ⚠ Failed: {r.get('error', 'Unknown error')}")

        return successes

    except Exception as e:
        print(f"      ✗ Error upserting batch: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Sync embeddings from production PostgreSQL to Typesense")
    parser.add_argument("--start-date", type=str, default="2025-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size for sync")
    parser.add_argument("--max-records", type=int, default=None, help="Max records to sync (for testing)")
    parser.add_argument("--full-sync", action="store_true", help="Sync all records (ignore last sync)")
    args = parser.parse_args()

    print("=" * 60)
    print("🔄 Sync Embeddings: Production PostgreSQL → Production Typesense")
    print("=" * 60)
    print(f"   Date range: {args.start_date} to {args.end_date}")

    # Start Cloud SQL Proxy
    proxy = start_cloud_sql_proxy()
    atexit.register(stop_cloud_sql_proxy, proxy)

    # Handle signals for cleanup
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # Get production credentials
    print("\n🔑 Fetching credentials from Secret Manager...")
    prod_password = get_secret(SECRET_PASSWORD)
    typesense_config = json.loads(get_secret(TYPESENSE_WRITE_SECRET))
    print("   ✓ Got PostgreSQL password")
    print(f"   ✓ Got Typesense write config (host: {typesense_config['host']})")

    # Build production PostgreSQL URL
    escaped_password = quote_plus(prod_password)
    prod_url = f"postgresql://{CLOUD_SQL_USER}:{escaped_password}@localhost:{CLOUD_SQL_PROXY_PORT}/{CLOUD_SQL_DATABASE}"

    # Connect to production PostgreSQL
    print("\n🔌 Connecting to production PostgreSQL...")
    try:
        pg_conn = get_pg_connection(prod_url)
        print("   ✓ Connected to PostgreSQL")
    except Exception as e:
        print(f"   ✗ Failed to connect: {e}")
        sys.exit(1)

    # Connect to Typesense
    print("\n🔌 Connecting to production Typesense...")
    try:
        ts_client = get_typesense_client(typesense_config)
        check_typesense_collection(ts_client)
    except Exception as e:
        print(f"   ✗ Failed to connect: {e}")
        sys.exit(1)

    # Count embeddings in PostgreSQL
    pg_count = count_embeddings_in_pg(pg_conn, args.start_date, args.end_date)
    print(f"\n📊 Embeddings in PostgreSQL: {pg_count:,}")

    if pg_count == 0:
        print("\n❌ No embeddings found in PostgreSQL for the date range")
        sys.exit(1)

    # Determine total records to sync
    total_to_sync = min(pg_count, args.max_records) if args.max_records else pg_count
    print(f"\n📤 Syncing {total_to_sync:,} embeddings to Typesense...")

    # Sync in batches
    synced = 0
    offset = 0
    batch_size = args.batch_size
    failed = 0

    with tqdm(total=total_to_sync, desc="   Syncing") as pbar:
        while synced < total_to_sync:
            # Fetch from PostgreSQL
            records = fetch_news_with_embeddings(
                pg_conn,
                args.start_date,
                args.end_date,
                min(batch_size, total_to_sync - synced),
                offset
            )

            if not records:
                break

            # Prepare documents
            documents = [prepare_typesense_document(r) for r in records]

            # Filter out documents without embeddings
            documents = [d for d in documents if d.get('content_embedding')]

            if documents:
                try:
                    successful = upsert_documents_batch(ts_client, documents)
                    synced += successful
                    failed += (len(documents) - successful)
                    pbar.update(successful)
                except Exception as e:
                    print(f"\n   ✗ Error syncing batch: {e}")
                    failed += len(documents)

            offset += len(records)

    # Get final Typesense count
    try:
        collection = ts_client.collections[COLLECTION_NAME].retrieve()
        ts_count = collection['num_documents']
    except:
        ts_count = "unknown"

    print("\n" + "=" * 60)
    print("✅ Sync completed!")
    print("=" * 60)
    print(f"   Records synced: {synced:,}")
    print(f"   Records failed: {failed:,}")
    print(f"   Typesense total documents: {ts_count}")
    print("=" * 60)

    pg_conn.close()


if __name__ == "__main__":
    main()
