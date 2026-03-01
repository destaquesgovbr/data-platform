"""Sync PostgreSQL news + features to BigQuery Gold layer."""

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# BigQuery target
DATASET_ID = "dgb_gold"
TABLE_ID = "fato_noticias"
FULL_TABLE_ID = f"{DATASET_ID}.{TABLE_ID}"

# SQL query: join news with news_features
SYNC_QUERY = """
    SELECT
        n.unique_id,
        n.title,
        n.url,
        n.agency_key,
        n.agency_name,
        t1.code AS theme_l1_code,
        t1.label AS theme_l1_label,
        t2.code AS theme_l2_code,
        t2.label AS theme_l2_label,
        tm.code AS most_specific_theme_code,
        tm.label AS most_specific_theme_label,
        n.published_at,
        n.extracted_at,
        NOW() AS synced_at,
        (nf.features->>'word_count')::int AS word_count,
        (nf.features->>'char_count')::int AS char_count,
        (nf.features->>'paragraph_count')::int AS paragraph_count,
        (nf.features->>'has_image')::boolean AS has_image,
        (nf.features->>'has_video')::boolean AS has_video,
        (nf.features->'sentiment'->>'score')::float AS sentiment_score,
        nf.features->'sentiment'->>'label' AS sentiment_label,
        (nf.features->>'publication_hour')::int AS publication_hour,
        (nf.features->>'publication_dow')::int AS publication_dow,
        (nf.features->>'readability_flesch')::float AS readability_flesch
    FROM news n
    LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
    LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
    LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
    LEFT JOIN news_features nf ON n.unique_id = nf.unique_id
    WHERE n.published_at >= %s
      AND n.published_at < %s::date + INTERVAL '1 day'
    ORDER BY n.published_at DESC
"""


def fetch_news_for_bigquery(
    db_url: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch news + features from PostgreSQL for BigQuery sync.

    Args:
        db_url: PostgreSQL connection string
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with denormalized news data
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(db_url, poolclass=NullPool)
    df = pd.read_sql_query(SYNC_QUERY, engine, params=(start_date, end_date))
    engine.dispose()

    logger.info(f"Fetched {len(df)} rows from PG ({start_date} to {end_date})")
    return df


def write_to_parquet_gcs(
    df: pd.DataFrame,
    bucket_name: str,
    date_str: str,
) -> str:
    """Write DataFrame to Parquet in GCS silver/analytics/ path.

    Args:
        df: DataFrame to write
        bucket_name: GCS bucket name
        date_str: Date string for partitioning (YYYY-MM-DD)

    Returns:
        GCS URI of the written file
    """
    from google.cloud import storage

    gcs_path = f"silver/analytics/{date_str}.parquet"
    gcs_uri = f"gs://{bucket_name}/{gcs_path}"

    # Write to local temp, then upload
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        df.to_parquet(tmp.name, index=False, engine="pyarrow")
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(tmp.name)

    logger.info(f"Written {len(df)} rows to {gcs_uri}")
    return gcs_uri


def load_parquet_to_bigquery(
    gcs_uri: str,
    project_id: str,
) -> int:
    """Load Parquet from GCS into BigQuery fato_noticias table.

    Args:
        gcs_uri: GCS URI of the Parquet file
        project_id: GCP project ID

    Returns:
        Number of rows loaded
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    table_ref = f"{project_id}.{FULL_TABLE_ID}"
    load_job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    load_job.result()  # Wait for completion

    logger.info(f"Loaded {load_job.output_rows} rows into {table_ref}")
    return load_job.output_rows


def sync_dimensions(db_url: str, project_id: str) -> None:
    """Sync dimension tables (agencies, themes) from PG to BigQuery.

    Full replace — dimensions are small and change rarely.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    engine = create_engine(db_url, poolclass=NullPool)

    # dim_agencias
    df_agencies = pd.read_sql_query(
        "SELECT key AS agency_key, name AS agency_name, type AS agency_type, parent_key FROM agencies",
        engine,
    )
    job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    client.load_table_from_dataframe(
        df_agencies, f"{project_id}.{DATASET_ID}.dim_agencias", job_config=job_config
    ).result()
    logger.info(f"Synced {len(df_agencies)} agencies to dim_agencias")

    # dim_temas
    df_themes = pd.read_sql_query(
        "SELECT code, label, full_name, level, parent_code FROM themes",
        engine,
    )
    client.load_table_from_dataframe(
        df_themes, f"{project_id}.{DATASET_ID}.dim_temas", job_config=job_config
    ).result()
    logger.info(f"Synced {len(df_themes)} themes to dim_temas")

    engine.dispose()
