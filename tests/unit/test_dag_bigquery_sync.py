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


@pytest.mark.skipif(
    not _airflow_available(),
    reason="Airflow not installed (runs in Cloud Composer only)",
)
class TestDagStructure:
    """Tests for the DAG definition — only runs when Airflow is available."""

    def test_dag_exists_and_has_correct_schedule(self):
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.dag_id == "sync_pg_to_bigquery"

    def test_dag_has_tasks(self):
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        task_ids = [t.task_id for t in dag_instance.tasks]
        assert "sync_facts" in task_ids
        assert "sync_dims" in task_ids

    def test_dag_catchup_disabled(self):
        from data_platform.dags.sync_pg_to_bigquery import dag_instance

        assert dag_instance.catchup is False
