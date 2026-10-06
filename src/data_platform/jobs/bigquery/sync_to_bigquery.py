"""Sync PostgreSQL news + features to BigQuery Gold layer."""

import logging

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


# Schema de load do dgb_gold.fato_noticias: (coluna, tipo BigQuery, modo).
# Fonte única do LoadJobConfig, dos dtypes do parquet e da ordem das colunas
# (igual ao SELECT do SYNC_QUERY e ao scripts/bigquery/create_tables.sql; os
# testes conferem os três).
FATO_NOTICIAS_SCHEMA: tuple[tuple[str, str, str], ...] = (
    ("unique_id", "STRING", "REQUIRED"),
    ("title", "STRING", "NULLABLE"),
    ("url", "STRING", "NULLABLE"),
    ("content_hash", "STRING", "NULLABLE"),
    ("agency_key", "STRING", "NULLABLE"),
    ("agency_name", "STRING", "NULLABLE"),
    ("theme_l1_code", "STRING", "NULLABLE"),
    ("theme_l1_label", "STRING", "NULLABLE"),
    ("theme_l2_code", "STRING", "NULLABLE"),
    ("theme_l2_label", "STRING", "NULLABLE"),
    ("most_specific_theme_code", "STRING", "NULLABLE"),
    ("most_specific_theme_label", "STRING", "NULLABLE"),
    ("published_at", "TIMESTAMP", "REQUIRED"),
    ("extracted_at", "TIMESTAMP", "NULLABLE"),
    ("synced_at", "TIMESTAMP", "REQUIRED"),
    ("word_count", "INTEGER", "NULLABLE"),
    ("char_count", "INTEGER", "NULLABLE"),
    ("paragraph_count", "INTEGER", "NULLABLE"),
    ("has_image", "BOOLEAN", "NULLABLE"),
    ("has_video", "BOOLEAN", "NULLABLE"),
    ("sentiment_score", "FLOAT", "NULLABLE"),
    ("sentiment_label", "STRING", "NULLABLE"),
    ("publication_hour", "INTEGER", "NULLABLE"),
    ("publication_dow", "INTEGER", "NULLABLE"),
    ("readability_flesch", "FLOAT", "NULLABLE"),
)

_FATO_COLUMNS: tuple[str, ...] = tuple(name for name, _, _ in FATO_NOTICIAS_SCHEMA)

# Tipo BigQuery → dtype nulável do pandas (TIMESTAMP vai por pd.to_datetime).
_PANDAS_DTYPES: dict[str, str] = {
    "STRING": "string",
    "INTEGER": "Int64",
    "FLOAT": "Float64",
    "BOOLEAN": "boolean",
}


# Caminho GraphQL: coluna ← campo de BigQueryRecordType (query newsBatchForBigquery).
# Todo campo precisa estar selecionado em NEWS_BATCH_FOR_BIGQUERY_QUERY (teste de contrato).
_BIGQUERY_GRAPHQL_FIELDS: dict[str, str] = {
    "unique_id": "uniqueId",
    "title": "title",
    "url": "url",
    "agency_key": "agencyKey",
    "agency_name": "agencyName",
    "theme_l1_code": "themeL1Code",
    "theme_l1_label": "themeL1Label",
    "theme_l2_code": "themeL2Code",
    "theme_l2_label": "themeL2Label",
    "most_specific_theme_code": "mostSpecificThemeCode",
    "most_specific_theme_label": "mostSpecificThemeLabel",
    "published_at": "publishedAt",
    "extracted_at": "extractedAt",
    "word_count": "wordCount",
    "has_image": "hasImage",
    "has_video": "hasVideo",
    "sentiment_score": "sentimentScore",
    "sentiment_label": "sentimentLabel",
    "readability_flesch": "readabilityFlesch",
}

# Colunas sem campo em BigQueryRecordType: lidas do blob `features`, com a mesma
# chave que o SYNC_QUERY lê de news_features.features.
_BIGQUERY_FEATURE_FIELDS: tuple[str, ...] = (
    "char_count",
    "paragraph_count",
    "publication_hour",
    "publication_dow",
)


def previous_day_window(logical_date) -> tuple[str, str]:
    """Janela de 1 dia para a execução diária: só o dia anterior ao logical_date.

    Retorna (start, end) para fetch_news_for_bigquery, que trata ``end`` como
    inclusivo (``< end + 1 dia``); com start == end a janela é exatamente
    [D-1, D) e execuções consecutivas não se sobrepõem.
    """
    from datetime import timedelta

    day = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
    return day, day


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


def coerce_to_load_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Colunas do FATO_NOTICIAS_SCHEMA, na ordem do load, com dtypes nuláveis.

    Sem isso, uma coluna inteira NULL (dtype object no read_sql) vira o tipo
    ``null`` do pyarrow, gravado como INT32 no parquet, e o load falha com
    "Parquet column 'has_image' has type INT32 which does not match the target
    cpp_type BOOL" (incidente de jun–out/2026).

    Raises:
        ValueError: se faltar alguma coluna do schema.
    """
    missing = [c for c in _FATO_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas ausentes para o load do fato_noticias: {missing}")
    extra = [c for c in df.columns if c not in _FATO_COLUMNS]
    if extra:
        logger.warning(f"Colunas fora do schema de load descartadas: {extra}")

    columns: dict[str, pd.Series] = {}
    for name, bq_type, _mode in FATO_NOTICIAS_SCHEMA:
        if bq_type == "TIMESTAMP":
            # ISO8601: o caminho GraphQL entrega str com e sem microssegundos.
            columns[name] = pd.to_datetime(df[name], utc=True, format="ISO8601")
        else:
            columns[name] = df[name].astype(_PANDAS_DTYPES[bq_type])
    return pd.DataFrame(columns, index=df.index)


def _arrow_load_schema():
    """Schema pyarrow equivalente ao FATO_NOTICIAS_SCHEMA (todas as colunas nuláveis).

    TIMESTAMP em ns UTC; o writer converte para us (coerce_timestamps).
    """
    import pyarrow as pa

    arrow_types = {
        "STRING": pa.string(),
        "INTEGER": pa.int64(),
        "FLOAT": pa.float64(),
        "BOOLEAN": pa.bool_(),
        "TIMESTAMP": pa.timestamp("ns", tz="UTC"),
    }
    return pa.schema([pa.field(name, arrow_types[t]) for name, t, _ in FATO_NOTICIAS_SCHEMA])


def write_to_parquet_gcs(
    df: pd.DataFrame,
    bucket_name: str,
    date_str: str,
) -> str:
    """Write DataFrame to Parquet in GCS silver/analytics/ path.

    Os tipos do parquet seguem o FATO_NOTICIAS_SCHEMA (coerce_to_load_schema +
    schema pyarrow explícito), mesmo quando uma coluna vem inteira nula.

    Args:
        df: DataFrame to write
        bucket_name: GCS bucket name
        date_str: Date string for partitioning (YYYY-MM-DD)

    Returns:
        GCS URI of the written file
    """
    import tempfile

    import pyarrow as pa
    import pyarrow.parquet as pq
    from google.cloud import storage

    gcs_path = f"silver/analytics/{date_str}.parquet"
    gcs_uri = f"gs://{bucket_name}/{gcs_path}"

    table = pa.Table.from_pandas(
        coerce_to_load_schema(df),
        schema=_arrow_load_schema(),
        preserve_index=False,
    )

    # Write to local temp, then upload
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        pq.write_table(
            table,
            tmp.name,
            coerce_timestamps="us",
            allow_truncated_timestamps=True,
        )
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
        bigquery.SchemaField(name, bq_type, mode=mode)
        for name, bq_type, mode in FATO_NOTICIAS_SCHEMA
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
        batch = data.get("newsBatchForBigquery") or []

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

    # camelCase do GraphQL → colunas do SYNC_QUERY (mesmo shape do caminho PG).
    # content_hash não é exposto em BigQueryRecordType; synced_at faz o papel do NOW().
    synced_at = pd.Timestamp.now(tz="UTC")
    rows = [_graphql_record_to_row(r, synced_at) for r in all_rows]

    df = pd.DataFrame(rows, columns=list(_FATO_COLUMNS))
    logger.info(f"Fetched {len(df)} rows via GraphQL ({start_date} to {end_date})")
    return df


def _graphql_record_to_row(record: dict, synced_at: pd.Timestamp) -> dict:
    """Um item de newsBatchForBigquery → linha com as colunas do fato_noticias."""
    features = record.get("features")
    if not isinstance(features, dict):
        features = {}
    row: dict = dict.fromkeys(_FATO_COLUMNS)
    for column, field in _BIGQUERY_GRAPHQL_FIELDS.items():
        row[column] = record.get(field)
    for column in _BIGQUERY_FEATURE_FIELDS:
        row[column] = features.get(column)
    row["synced_at"] = synced_at
    return row


def sync_dimensions(db_url: str, project_id: str) -> None:
    """Sync dimension tables (agencies, themes) from PG to BigQuery.

    Full replace — dimensions are small and change rarely.
    """
    from google.cloud import bigquery
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

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
