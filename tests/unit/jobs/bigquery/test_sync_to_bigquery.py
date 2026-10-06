"""Unit tests for BigQuery sync DAG and job module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.jobs.bigquery.sync_to_bigquery import SYNC_QUERY


def _airflow_available():
    try:
        import airflow

        return True
    except ImportError:
        return False


class TestSyncQuery:
    """Tests for the SQL query used in BigQuery sync."""

    def test_query_has_required_columns(self):
        required = [
            "unique_id",
            "title",
            "agency_key",
            "published_at",
            "content_hash",
            "word_count",
            "sentiment_score",
            "sentiment_label",
            "has_image",
            "has_video",
            "readability_flesch",
            "theme_l1_code",
            "most_specific_theme_code",
        ]
        for col in required:
            assert col in SYNC_QUERY, f"Missing column: {col}"

    def test_query_joins_news_features(self):
        assert "news_features" in SYNC_QUERY
        assert "LEFT JOIN news_features" in SYNC_QUERY

    def test_query_filters_by_date(self):
        assert "published_at >= %s" in SYNC_QUERY
        assert "published_at <" in SYNC_QUERY


class TestFetchNewsForBigquery:
    """Tests for fetch_news_for_bigquery function."""

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_returns_dataframe(self, mock_read_sql, mock_engine):
        from data_platform.jobs.bigquery.sync_to_bigquery import fetch_news_for_bigquery

        mock_read_sql.return_value = pd.DataFrame({"unique_id": ["abc"]})
        mock_eng = MagicMock()
        mock_engine.return_value = mock_eng

        df = fetch_news_for_bigquery("postgresql://test", "2024-01-01", "2024-01-02")

        assert len(df) == 1
        mock_eng.dispose.assert_called_once()

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_passes_date_params(self, mock_read_sql, mock_engine):
        from data_platform.jobs.bigquery.sync_to_bigquery import fetch_news_for_bigquery

        mock_read_sql.return_value = pd.DataFrame()
        mock_engine.return_value = MagicMock()

        fetch_news_for_bigquery("postgresql://test", "2024-06-01", "2024-06-02")

        call_params = mock_read_sql.call_args[1].get("params") or mock_read_sql.call_args[0][2]
        assert "2024-06-01" in call_params
        assert "2024-06-02" in call_params


class TestSchemaConsistency:
    """Ensure BigQuery schema in code stays in sync with create_tables.sql."""

    def test_load_schema_matches_create_tables_ddl(self):
        """FATO_NOTICIAS_SCHEMA (nomes, tipos e NOT NULL) must match fato_noticias DDL."""
        import re
        from pathlib import Path

        from data_platform.jobs.bigquery.sync_to_bigquery import FATO_NOTICIAS_SCHEMA

        ddl_path = Path(__file__).parents[4] / "scripts" / "bigquery" / "create_tables.sql"
        ddl_text = ddl_path.read_text()
        match = re.search(
            r"CREATE TABLE.*?fato_noticias\s*\((.*?)\)\s*PARTITION BY",
            ddl_text,
            re.DOTALL | re.IGNORECASE,
        )
        assert match, "Could not parse fato_noticias from create_tables.sql"
        ddl = re.findall(r"^\s*(\w+)\s+(\w+)(\s+NOT NULL)?", match.group(1), re.MULTILINE)

        legacy_to_standard = {
            "STRING": "STRING",
            "INTEGER": "INT64",
            "FLOAT": "FLOAT64",
            "BOOLEAN": "BOOL",
            "TIMESTAMP": "TIMESTAMP",
        }
        code = [
            (name, legacy_to_standard[bq_type], " NOT NULL" if mode == "REQUIRED" else "")
            for name, bq_type, mode in FATO_NOTICIAS_SCHEMA
        ]
        assert code == ddl, f"Schema mismatch between code and DDL!\nCode: {code}\nDDL:  {ddl}"

    def test_sync_query_columns_match_load_schema(self):
        """SYNC_QUERY SELECT aliases must match FATO_NOTICIAS_SCHEMA."""
        import re

        from data_platform.jobs.bigquery.sync_to_bigquery import (
            FATO_NOTICIAS_SCHEMA,
            SYNC_QUERY,
        )

        select_match = re.search(r"SELECT\s+(.*?)\s+FROM\s+news", SYNC_QUERY, re.DOTALL)
        assert select_match, "Could not parse SELECT from SYNC_QUERY"
        query_columns = []
        for line in select_match.group(1).split(","):
            line = line.strip()
            if not line:
                continue
            as_match = re.search(r"\bAS\s+(\w+)\s*$", line, re.IGNORECASE)
            if as_match:
                query_columns.append(as_match.group(1))
            else:
                col_match = re.search(r"\.?(\w+)\s*$", line)
                if col_match:
                    query_columns.append(col_match.group(1))

        schema_columns = [name for name, _, _ in FATO_NOTICIAS_SCHEMA]

        assert query_columns == schema_columns, (
            f"SYNC_QUERY columns don't match FATO_NOTICIAS_SCHEMA!\n"
            f"Query  ({len(query_columns)}): {query_columns}\n"
            f"Schema ({len(schema_columns)}): {schema_columns}"
        )

    @patch("google.cloud.bigquery.Client")
    def test_load_job_usa_o_schema_unico(self, mock_client_cls):
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            FATO_NOTICIAS_SCHEMA,
            load_parquet_to_bigquery,
        )

        mock_client = mock_client_cls.return_value
        mock_client.load_table_from_uri.return_value.output_rows = 3

        rows = load_parquet_to_bigquery("gs://b/silver/analytics/2026-10-05.parquet", "proj")

        job_config = mock_client.load_table_from_uri.call_args[1]["job_config"]
        loaded = [(f.name, f.field_type, f.mode) for f in job_config.schema]
        assert loaded == list(FATO_NOTICIAS_SCHEMA)
        assert rows == 3


class TestDagStructure:
    """Tests for the DAG definition — only runs when Airflow is available."""

    def test_dag_exists_and_has_correct_schedule(self):
        pytest.importorskip(
            "airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)"
        )
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.dag_id == "sync_pg_to_bigquery"

    def test_dag_has_tasks(self):
        pytest.importorskip(
            "airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)"
        )
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        task_ids = [t.task_id for t in dag_instance.tasks]
        assert "sync_facts" in task_ids
        assert "sync_dims" in task_ids

    def test_dag_catchup_disabled(self):
        pytest.importorskip(
            "airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)"
        )
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.catchup is False

    def test_dag_does_not_have_ensure_schema_task(self):
        """ensure_schema was a workaround removed in issue #163."""
        pytest.importorskip(
            "airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)"
        )
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        task_ids = [t.task_id for t in dag_instance.tasks]
        assert "ensure_schema" not in task_ids

    def test_sync_tasks_have_no_upstream(self):
        """After removing ensure_schema, sync tasks have no upstream deps."""
        pytest.importorskip(
            "airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)"
        )
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        for task in dag_instance.tasks:
            assert len(task.upstream_list) == 0


# =============================================================================
# Caminho GraphQL (newsBatchForBigquery), inerte enquanto GRAPHQL_API_URL faltar
# =============================================================================

# Colunas do SYNC_QUERY (caminho PG), na ordem do schema de load.
_FATO_COLUMNS = [
    "unique_id",
    "title",
    "url",
    "content_hash",
    "agency_key",
    "agency_name",
    "theme_l1_code",
    "theme_l1_label",
    "theme_l2_code",
    "theme_l2_label",
    "most_specific_theme_code",
    "most_specific_theme_label",
    "published_at",
    "extracted_at",
    "synced_at",
    "word_count",
    "char_count",
    "paragraph_count",
    "has_image",
    "has_video",
    "sentiment_score",
    "sentiment_label",
    "publication_hour",
    "publication_dow",
    "readability_flesch",
]


def _bq_record(unique_id: str = "mec-1", **overrides) -> dict:
    """Item de newsBatchForBigquery com os campos que existem em BigQueryRecordType."""
    record = {
        "uniqueId": unique_id,
        "title": f"Título {unique_id}",
        "url": f"https://gov.br/{unique_id}",
        "agencyKey": "mec",
        "agencyName": "Ministério da Educação",
        "publishedAt": "2025-06-01T10:00:00+00:00",
        "extractedAt": "2025-06-01T11:00:00+00:00",
        "themeL1Code": "06",
        "themeL1Label": "Educação",
        "themeL2Code": "06.01",
        "themeL2Label": "Ensino Superior",
        "mostSpecificThemeCode": "06.01",
        "mostSpecificThemeLabel": "Ensino Superior",
        "wordCount": 300,
        "hasImage": True,
        "hasVideo": False,
        "sentimentLabel": "positive",
        "sentimentScore": 0.8,
        "readabilityFlesch": 35.5,
        "features": {
            "word_count": 300,
            "char_count": 1500,
            "paragraph_count": 5,
            "publication_hour": 10,
            "publication_dow": 6,
            "has_image": True,
        },
    }
    record.update(overrides)
    return record


class TestFetchNewsForBigqueryViaGraphql:
    def test_le_o_campo_newsBatchForBigquery(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": [_bq_record("a"), _bq_record("b")]}

        df = fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02")

        assert list(df["unique_id"]) == ["a", "b"]

    def test_datas_enviadas_como_string(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": []}

        fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02")

        variables = gql.query.call_args[0][1]
        assert variables["startDate"] == "2025-06-01"
        assert variables["endDate"] == "2025-06-02"

    def test_mapeia_themeL(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": [_bq_record()]}

        row = fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02").iloc[0]

        assert row["theme_l1_code"] == "06"
        assert row["theme_l1_label"] == "Educação"
        assert row["theme_l2_code"] == "06.01"
        assert row["theme_l2_label"] == "Ensino Superior"
        assert row["most_specific_theme_code"] == "06.01"

    def test_campos_ausentes_no_schema_saem_de_features(self):
        """charCount/paragraphCount/publicationHour/publicationDow não existem no SDL."""
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": [_bq_record()]}

        row = fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02").iloc[0]

        assert row["char_count"] == 1500
        assert row["paragraph_count"] == 5
        assert row["publication_hour"] == 10
        assert row["publication_dow"] == 6
        assert row["word_count"] == 300
        assert row["readability_flesch"] == 35.5

    def test_features_nulo_vira_colunas_nulas(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": [_bq_record(features=None)]}

        row = fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02").iloc[0]

        assert pd.isna(row["char_count"])
        assert pd.isna(row["publication_hour"])

    def test_mesmas_colunas_do_caminho_pg(self):
        """Mesmo shape do SYNC_QUERY: o parquet carrega no mesmo schema (synced_at é REQUIRED)."""
        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {"newsBatchForBigquery": [_bq_record()]}

        df = fetch_news_for_bigquery_via_graphql(gql, "2025-06-01", "2025-06-02")

        assert list(df.columns) == _FATO_COLUMNS
        assert df.iloc[0]["synced_at"] is not None
        assert pd.isna(df.iloc[0]["content_hash"])  # não exposto em BigQueryRecordType
        assert df.iloc[0]["extracted_at"] == "2025-06-01T11:00:00+00:00"


# =============================================================================
# Parquet com os tipos do schema de load (incidente has_image INT32, out/2026)
# =============================================================================
#
# O sync_facts falhou >=30 dias com "Parquet column 'has_image' has type INT32
# which does not match the target cpp_type BOOL": sem features desde ~26/05, a
# coluna veio inteira NULL do read_sql (dtype object) e o pyarrow a gravou como
# tipo null (INT32 físico).


def _pg_like_frame(n: int = 2, **columns) -> pd.DataFrame:
    """DataFrame como o read_sql devolve: colunas object com None onde não há dado."""
    from datetime import UTC, datetime

    base = {name: [None] * n for name in _FATO_COLUMNS}
    base["unique_id"] = [f"mec-{i}" for i in range(n)]
    base["published_at"] = [datetime(2026, 10, 5, 12, 0, tzinfo=UTC)] * n
    base["synced_at"] = [datetime(2026, 10, 6, 7, 0, tzinfo=UTC)] * n
    base.update(columns)
    return pd.DataFrame(base).astype(object)


def _write_and_capture(df: pd.DataFrame):
    """Roda write_to_parquet_gcs com o GCS mockado e devolve o ParquetFile gravado."""
    import io

    import pyarrow.parquet as pq

    from data_platform.jobs.bigquery.sync_to_bigquery import write_to_parquet_gcs

    captured: dict = {}

    def _upload(path):
        with open(path, "rb") as fh:
            captured["bytes"] = fh.read()

    with patch("google.cloud.storage.Client") as mock_client:
        blob = mock_client.return_value.bucket.return_value.blob.return_value
        blob.upload_from_filename.side_effect = _upload
        uri = write_to_parquet_gcs(df, "bucket-x", "2026-10-05")

    assert uri == "gs://bucket-x/silver/analytics/2026-10-05.parquet"
    return pq.ParquetFile(io.BytesIO(captured["bytes"]))


class TestParquetDtypes:
    def test_coluna_bool_toda_nula_sai_como_boolean(self):
        parquet = _write_and_capture(_pg_like_frame())

        physical = {c.name: c.physical_type for c in parquet.schema}
        assert physical["has_image"] == "BOOLEAN"
        assert physical["has_video"] == "BOOLEAN"

    def test_todas_as_colunas_seguem_o_schema_de_load_mesmo_todo_nulas(self):
        import pyarrow as pa

        from data_platform.jobs.bigquery.sync_to_bigquery import FATO_NOTICIAS_SCHEMA

        arrow = _write_and_capture(_pg_like_frame()).schema_arrow

        expected = {
            "STRING": pa.string(),
            "INTEGER": pa.int64(),
            "FLOAT": pa.float64(),
            "BOOLEAN": pa.bool_(),
            "TIMESTAMP": pa.timestamp("us", tz="UTC"),
        }
        assert arrow.names == [name for name, _, _ in FATO_NOTICIAS_SCHEMA]
        for name, bq_type, _ in FATO_NOTICIAS_SCHEMA:
            assert arrow.field(name).type == expected[bq_type], name

    def test_valores_preservados(self):
        import math
        from datetime import UTC, datetime

        df = _pg_like_frame(
            n=3,
            title=["a", None, "c"],
            word_count=[300, None, 5],
            has_image=[True, None, False],
            sentiment_score=[0.25, None, -0.5],
            readability_flesch=[None, None, 33.5],
            extracted_at=[datetime(2026, 10, 5, 13, 0, tzinfo=UTC), None, None],
        )

        table = _write_and_capture(df).read()

        assert table.column("title").to_pylist() == ["a", None, "c"]
        assert table.column("word_count").to_pylist() == [300, None, 5]
        assert table.column("has_image").to_pylist() == [True, None, False]
        assert table.column("sentiment_score").to_pylist() == [0.25, None, -0.5]
        assert table.column("readability_flesch").to_pylist() == [None, None, 33.5]
        assert table.column("extracted_at").to_pylist()[0] == datetime(
            2026, 10, 5, 13, 0, tzinfo=UTC
        )
        assert not any(
            isinstance(v, float) and math.isnan(v)
            for v in table.column("sentiment_score").to_pylist()
        )

    def test_float_com_nan_vira_int64_nulavel(self):
        """read_sql devolve float64 com NaN quando a coluna inteira tem nulos parciais."""
        df = _pg_like_frame(n=2)
        df["word_count"] = pd.Series([300.0, float("nan")])

        table = _write_and_capture(df).read()

        assert table.column("word_count").to_pylist() == [300, None]

    def test_coerce_devolve_dtypes_nulaveis_do_pandas(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import coerce_to_load_schema

        out = coerce_to_load_schema(_pg_like_frame())

        assert str(out["has_image"].dtype) == "boolean"
        assert str(out["word_count"].dtype) == "Int64"
        assert str(out["sentiment_score"].dtype) == "Float64"
        assert str(out["title"].dtype) == "string"
        assert str(out["published_at"].dtype) == "datetime64[ns, UTC]"

    def test_coluna_faltando_falha_cedo(self):
        from data_platform.jobs.bigquery.sync_to_bigquery import coerce_to_load_schema

        with pytest.raises(ValueError, match="has_image"):
            coerce_to_load_schema(_pg_like_frame().drop(columns=["has_image"]))

    def test_caminho_graphql_gera_parquet_no_schema(self):
        """Datas ISO (str) do GraphQL viram TIMESTAMP; features ausentes, nulos tipados."""
        import pyarrow as pa

        from data_platform.jobs.bigquery.sync_to_bigquery import (
            fetch_news_for_bigquery_via_graphql,
        )

        gql = MagicMock()
        gql.query.return_value = {
            "newsBatchForBigquery": [_bq_record("a", features=None, hasImage=None, hasVideo=None)]
        }
        df = fetch_news_for_bigquery_via_graphql(gql, "2026-10-05", "2026-10-06")

        arrow = _write_and_capture(df).schema_arrow

        assert arrow.field("published_at").type == pa.timestamp("us", tz="UTC")
        assert arrow.field("synced_at").type == pa.timestamp("us", tz="UTC")
        assert arrow.field("has_image").type == pa.bool_()
        assert arrow.field("char_count").type == pa.int64()
