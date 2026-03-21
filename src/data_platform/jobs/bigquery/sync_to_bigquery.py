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
        n.content_hash,
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

    # Cast nullable int columns to Int64 (Pandas nullable integer) so Parquet
    # writes them as INT64 instead of DOUBLE when NaN values are present.
    int_cols = ["word_count", "char_count", "paragraph_count", "publication_hour", "publication_dow"]
    for col in int_cols:
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    # Write to local temp, then upload
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        df.to_parquet(tmp.name, index=False, engine="pyarrow", coerce_timestamps="us", allow_truncated_timestamps=True)
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

    schema = [
        bigquery.SchemaField("unique_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("title", "STRING"),
        bigquery.SchemaField("url", "STRING"),
        bigquery.SchemaField("content_hash", "STRING"),
        bigquery.SchemaField("agency_key", "STRING"),
        bigquery.SchemaField("agency_name", "STRING"),
        bigquery.SchemaField("theme_l1_code", "STRING"),
        bigquery.SchemaField("theme_l1_label", "STRING"),
        bigquery.SchemaField("theme_l2_code", "STRING"),
        bigquery.SchemaField("theme_l2_label", "STRING"),
        bigquery.SchemaField("most_specific_theme_code", "STRING"),
        bigquery.SchemaField("most_specific_theme_label", "STRING"),
        bigquery.SchemaField("published_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("extracted_at", "TIMESTAMP"),
        bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("word_count", "INTEGER"),
        bigquery.SchemaField("char_count", "INTEGER"),
        bigquery.SchemaField("paragraph_count", "INTEGER"),
        bigquery.SchemaField("has_image", "BOOLEAN"),
        bigquery.SchemaField("has_video", "BOOLEAN"),
        bigquery.SchemaField("sentiment_score", "FLOAT"),
        bigquery.SchemaField("sentiment_label", "STRING"),
        bigquery.SchemaField("publication_hour", "INTEGER"),
        bigquery.SchemaField("publication_dow", "INTEGER"),
        bigquery.SchemaField("readability_flesch", "FLOAT"),
    ]

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=schema,
    )

    table_ref = f"{project_id}.{FULL_TABLE_ID}"
    load_job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    load_job.result()  # Wait for completion

    logger.info(f"Loaded {load_job.output_rows} rows into {table_ref}")
    return load_job.output_rows


def fetch_news_for_bigquery_via_graphql(
    gql_client,
    start_date: str,
    end_date: str,
    batch_size: int = 500,
) -> pd.DataFrame:
    """Fetch news + features from PostgreSQL via GraphQL for BigQuery sync.

    Uses paginated NEWS_BATCH_FOR_BIGQUERY_QUERY with cursor-based pagination.

    Args:
        gql_client: GraphQLClient instance
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        batch_size: Number of records per page

    Returns:
        DataFrame with denormalized news data (same shape as fetch_news_for_bigquery)
    """
    from data_platform.clients.graphql_client import NEWS_BATCH_FOR_BIGQUERY_QUERY

    all_rows: list[dict] = []
    cursor: str | None = None

    while True:
        variables: dict = {
            "startDate": start_date,
            "endDate": end_date,
            "batchSize": batch_size,
        }
        if cursor is not None:
            variables["cursor"] = cursor

        data = gql_client.query(NEWS_BATCH_FOR_BIGQUERY_QUERY, variables)
        batch = data.get("newsBatchForBigQuery", [])

        if not batch:
            break

        all_rows.extend(batch)

        # Use last item's uniqueId as cursor for next page
        cursor = batch[-1]["uniqueId"]

        # If we got fewer than batch_size, we've reached the end
        if len(batch) < batch_size:
            break

    if not all_rows:
        logger.info(f"No data via GraphQL for {start_date} to {end_date}")
        return pd.DataFrame()

    # Convert camelCase GraphQL response to snake_case DataFrame columns
    rows = []
    for r in all_rows:
        rows.append({
            "unique_id": r.get("uniqueId"),
            "title": r.get("title"),
            "url": r.get("url"),
            "agency_key": r.get("agencyKey"),
            "agency_name": r.get("agencyName"),
            "published_at": r.get("publishedAt"),
            "theme_l1_code": r.get("themL1Code"),
            "theme_l1_label": r.get("themL1Label"),
            "theme_l2_code": r.get("themL2Code"),
            "theme_l2_label": r.get("themL2Label"),
            "most_specific_theme_code": r.get("mostSpecificThemeCode"),
            "most_specific_theme_label": r.get("mostSpecificThemeLabel"),
            "word_count": r.get("wordCount"),
            "char_count": r.get("charCount"),
            "paragraph_count": r.get("paragraphCount"),
            "has_image": r.get("hasImage"),
            "has_video": r.get("hasVideo"),
            "sentiment_label": r.get("sentimentLabel"),
            "sentiment_score": r.get("sentimentScore"),
            "readability_flesch": r.get("readabilityFlesch"),
            "publication_hour": r.get("publicationHour"),
            "publication_dow": r.get("publicationDow"),
        })

    df = pd.DataFrame(rows)
    logger.info(f"Fetched {len(df)} rows via GraphQL ({start_date} to {end_date})")
    return df


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
