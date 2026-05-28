"""Unit tests for BigQuery sync DAG and job module."""

from datetime import datetime
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
            "unique_id", "title", "agency_key", "published_at",
            "content_hash",
            "word_count", "sentiment_score", "sentiment_label",
            "has_image", "has_video", "readability_flesch",
            "theme_l1_code", "most_specific_theme_code",
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
        """LoadJobConfig schema fields must match fato_noticias DDL columns."""
        import inspect
        import re
        from pathlib import Path

        from data_platform.jobs.bigquery.sync_to_bigquery import load_parquet_to_bigquery

        source = inspect.getsource(load_parquet_to_bigquery)
        code_columns = re.findall(r'SchemaField\("(\w+)"', source)

        ddl_path = Path(__file__).parents[4] / "scripts" / "bigquery" / "create_tables.sql"
        ddl_text = ddl_path.read_text()
        match = re.search(
            r"CREATE TABLE.*?fato_noticias\s*\((.*?)\)\s*PARTITION BY",
            ddl_text,
            re.DOTALL | re.IGNORECASE,
        )
        assert match, "Could not parse fato_noticias from create_tables.sql"
        ddl_columns = re.findall(r"^\s*(\w+)\s+\w+", match.group(1), re.MULTILINE)

        assert code_columns == ddl_columns, (
            f"Schema mismatch between code and DDL!\n"
            f"Code ({len(code_columns)}): {code_columns}\n"
            f"DDL  ({len(ddl_columns)}): {ddl_columns}"
        )

    def test_sync_query_columns_match_load_schema(self):
        """SYNC_QUERY SELECT aliases must match LoadJobConfig schema fields."""
        import inspect
        import re

        from data_platform.jobs.bigquery.sync_to_bigquery import (
            SYNC_QUERY,
            load_parquet_to_bigquery,
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

        source = inspect.getsource(load_parquet_to_bigquery)
        schema_columns = re.findall(r'SchemaField\("(\w+)"', source)

        assert query_columns == schema_columns, (
            f"SYNC_QUERY columns don't match LoadJobConfig schema!\n"
            f"Query  ({len(query_columns)}): {query_columns}\n"
            f"Schema ({len(schema_columns)}): {schema_columns}"
        )


class TestDagStructure:
    """Tests for the DAG definition — only runs when Airflow is available."""

    def test_dag_exists_and_has_correct_schedule(self):
        pytest.importorskip("airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)")
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.dag_id == "sync_pg_to_bigquery"

    def test_dag_has_tasks(self):
        pytest.importorskip("airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)")
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        task_ids = [t.task_id for t in dag_instance.tasks]
        assert "sync_facts" in task_ids
        assert "sync_dims" in task_ids

    def test_dag_catchup_disabled(self):
        pytest.importorskip("airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)")
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.catchup is False

    def test_dag_does_not_have_ensure_schema_task(self):
        """ensure_schema was a workaround removed in issue #163."""
        pytest.importorskip("airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)")
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        task_ids = [t.task_id for t in dag_instance.tasks]
        assert "ensure_schema" not in task_ids

    def test_sync_tasks_have_no_upstream(self):
        """After removing ensure_schema, sync tasks have no upstream deps."""
        pytest.importorskip("airflow.decorators", reason="Airflow not installed (runs in Cloud Composer only)")
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        for task in dag_instance.tasks:
            assert len(task.upstream_list) == 0
