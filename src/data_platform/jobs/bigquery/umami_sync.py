"""Sync Umami Analytics data from PostgreSQL to BigQuery."""

import json
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

PAGEVIEWS_QUERY = """
    SELECT
        we.event_id::text,
        we.session_id::text,
        we.visit_id::text,
        we.created_at,
        we.url_path,
        we.url_query,
        we.page_title,
        we.referrer_domain,
        we.referrer_path,
        we.hostname,
        we.utm_source,
        we.utm_medium,
        we.utm_campaign,
        s.browser,
        s.os,
        s.device,
        s.country,
        s.region,
        s.city,
        s.language
    FROM website_event we
    JOIN session s ON we.session_id = s.session_id
    WHERE we.event_type = 1
      AND we.created_at >= %s
      AND we.created_at < %s
    ORDER BY we.created_at
"""

EVENTS_QUERY = """
    SELECT
        we.event_id::text,
        we.session_id::text,
        we.created_at,
        we.event_name,
        we.url_path,
        we.hostname,
        s.browser,
        s.os,
        s.device,
        s.country,
        jsonb_object_agg(
            ed.data_key,
            COALESCE(ed.string_value, ed.number_value::text)
        ) FILTER (WHERE ed.data_key IS NOT NULL) AS event_data
    FROM website_event we
    JOIN session s ON we.session_id = s.session_id
    LEFT JOIN event_data ed ON we.event_id = ed.website_event_id
    WHERE we.event_type = 2
      AND we.created_at >= %s
      AND we.created_at < %s
    GROUP BY we.event_id, we.session_id, we.created_at,
             we.event_name, we.url_path, we.hostname,
             s.browser, s.os, s.device, s.country
    ORDER BY we.created_at
"""

# BigQuery schemas
PAGEVIEWS_SCHEMA = [
    ("event_id", "STRING", "REQUIRED"),
    ("session_id", "STRING", "REQUIRED"),
    ("visit_id", "STRING", "NULLABLE"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("url_path", "STRING", "NULLABLE"),
    ("url_query", "STRING", "NULLABLE"),
    ("page_title", "STRING", "NULLABLE"),
    ("referrer_domain", "STRING", "NULLABLE"),
    ("referrer_path", "STRING", "NULLABLE"),
    ("hostname", "STRING", "NULLABLE"),
    ("utm_source", "STRING", "NULLABLE"),
    ("utm_medium", "STRING", "NULLABLE"),
    ("utm_campaign", "STRING", "NULLABLE"),
    ("browser", "STRING", "NULLABLE"),
    ("os", "STRING", "NULLABLE"),
    ("device", "STRING", "NULLABLE"),
    ("country", "STRING", "NULLABLE"),
    ("region", "STRING", "NULLABLE"),
    ("city", "STRING", "NULLABLE"),
    ("language", "STRING", "NULLABLE"),
]

EVENTS_SCHEMA = [
    ("event_id", "STRING", "REQUIRED"),
    ("session_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("event_name", "STRING", "REQUIRED"),
    ("url_path", "STRING", "NULLABLE"),
    ("hostname", "STRING", "NULLABLE"),
    ("event_data", "JSON", "NULLABLE"),
    ("browser", "STRING", "NULLABLE"),
    ("os", "STRING", "NULLABLE"),
    ("device", "STRING", "NULLABLE"),
    ("country", "STRING", "NULLABLE"),
]


def get_umami_db_url(airflow_conn_id: str = "umami_postgres") -> str:
    """Build Umami database URL from Airflow connection.

    Uses a dedicated 'umami_postgres' Airflow connection.
    Builds the URL manually from connection fields to avoid URL-encoding
    issues with Cloud SQL socket paths (e.g. /cloudsql/...).

    Falls back to deriving from 'postgres_default' by swapping the database name.

    Args:
        airflow_conn_id: Airflow connection ID for Umami database

    Returns:
        SQLAlchemy-compatible connection string
    """
    from urllib.parse import quote_plus

    from airflow.hooks.base import BaseHook

    try:
        conn = BaseHook.get_connection(airflow_conn_id)
        logger.info(f"Using Airflow connection: {airflow_conn_id}")
    except Exception:
        logger.warning(
            f"Connection '{airflow_conn_id}' not found, "
            "deriving from 'postgres_default'"
        )
        conn = BaseHook.get_connection("postgres_default")

    login = quote_plus(conn.login or "")
    password = quote_plus(conn.password or "")
    host = conn.host or "localhost"
    port = conn.port or 5432
    schema = conn.schema or "umami"

    # Cloud SQL uses Unix socket paths (e.g. /cloudsql/project:region:instance)
    if host.startswith("/"):
        db_url = (
            f"postgresql://{login}:{password}@/{schema}"
            f"?host={host}&port={port}"
        )
    else:
        db_url = f"postgresql://{login}:{password}@{host}:{port}/{schema}"

    return db_url


def _serialize_row(row: dict) -> dict:
    """Serialize a database row for BigQuery JSON upload.

    Converts datetime objects to ISO strings and ensures
    event_data dicts become JSON strings.
    """
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif key == "event_data" and isinstance(value, dict):
            out[key] = json.dumps(value)
        else:
            out[key] = value
    return out


def _fetch_rows(db_url: str, query: str, params: tuple) -> list[dict]:
    """Execute a query against PostgreSQL and return rows as list of dicts."""
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            rows = [_serialize_row(dict(row)) for row in cur.fetchall()]
    finally:
        conn.close()
    return rows


def fetch_umami_pageviews(
    db_url: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch pageview events from Umami PostgreSQL.

    Args:
        db_url: Umami PostgreSQL connection string
        start_date: Start datetime (inclusive), ISO format
        end_date: End datetime (exclusive), ISO format

    Returns:
        List of dicts with pageview data joined with session info
    """
    rows = _fetch_rows(db_url, PAGEVIEWS_QUERY, (start_date, end_date))
    logger.info(
        f"Fetched {len(rows)} pageviews from Umami ({start_date} to {end_date})"
    )
    return rows


def fetch_umami_events(
    db_url: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch custom events from Umami PostgreSQL.

    Args:
        db_url: Umami PostgreSQL connection string
        start_date: Start datetime (inclusive), ISO format
        end_date: End datetime (exclusive), ISO format

    Returns:
        List of dicts with custom event data including event_data JSON
    """
    rows = _fetch_rows(db_url, EVENTS_QUERY, (start_date, end_date))
    logger.info(
        f"Fetched {len(rows)} custom events from Umami ({start_date} to {end_date})"
    )
    return rows


def load_to_bigquery(
    rows: list[dict],
    project_id: str,
    table_id: str,
    schema_fields: list[tuple[str, str, str]],
) -> int:
    """Load rows into BigQuery table using load_table_from_json.

    Args:
        rows: List of dicts to load
        project_id: GCP project ID
        table_id: Full table ID (dataset.table)
        schema_fields: List of (name, type, mode) tuples

    Returns:
        Number of rows loaded
    """
    if not rows:
        logger.info(f"No data to load into {table_id}")
        return 0

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)

    schema = [
        bigquery.SchemaField(name, field_type, mode=mode)
        for name, field_type, mode in schema_fields
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    full_table_id = f"{project_id}.{table_id}"
    load_job = client.load_table_from_json(
        rows, full_table_id, job_config=job_config
    )
    load_job.result()

    logger.info(f"Loaded {load_job.output_rows} rows into {full_table_id}")
    return load_job.output_rows
