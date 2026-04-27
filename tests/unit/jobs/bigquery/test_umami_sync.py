"""Unit tests for Umami Analytics sync to BigQuery."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.bigquery.umami_sync import (
    EVENTS_QUERY,
    EVENTS_SCHEMA,
    PAGEVIEWS_QUERY,
    PAGEVIEWS_SCHEMA,
    _serialize_row,
    fetch_umami_events,
    fetch_umami_pageviews,
    load_to_bigquery,
)


class TestPageviewsQuery:
    def test_filters_event_type_1(self):
        assert "we.event_type = 1" in PAGEVIEWS_QUERY

    def test_joins_session(self):
        assert "JOIN session s ON we.session_id = s.session_id" in PAGEVIEWS_QUERY

    def test_has_date_range_params(self):
        assert "we.created_at >= %s" in PAGEVIEWS_QUERY
        assert "we.created_at < %s" in PAGEVIEWS_QUERY

    def test_selects_session_fields(self):
        for field in ["s.browser", "s.os", "s.device", "s.country", "s.region", "s.city", "s.language"]:
            assert field in PAGEVIEWS_QUERY

    def test_selects_utm_fields(self):
        for field in ["we.utm_source", "we.utm_medium", "we.utm_campaign"]:
            assert field in PAGEVIEWS_QUERY

    def test_selects_url_fields(self):
        for field in ["we.url_path", "we.url_query", "we.page_title"]:
            assert field in PAGEVIEWS_QUERY

    def test_casts_uuids_to_text(self):
        assert "we.event_id::text" in PAGEVIEWS_QUERY
        assert "we.session_id::text" in PAGEVIEWS_QUERY
        assert "we.visit_id::text" in PAGEVIEWS_QUERY


class TestEventsQuery:
    def test_filters_event_type_2(self):
        assert "we.event_type = 2" in EVENTS_QUERY

    def test_joins_event_data(self):
        assert "LEFT JOIN event_data ed ON we.event_id = ed.website_event_id" in EVENTS_QUERY

    def test_aggregates_event_data_as_json(self):
        assert "jsonb_object_agg" in EVENTS_QUERY

    def test_filters_null_keys(self):
        assert "WHERE ed.data_key IS NOT NULL" in EVENTS_QUERY

    def test_groups_by_event_fields(self):
        assert "GROUP BY we.event_id" in EVENTS_QUERY

    def test_has_date_range_params(self):
        assert "we.created_at >= %s" in EVENTS_QUERY
        assert "we.created_at < %s" in EVENTS_QUERY


class TestSchemas:
    def test_pageviews_schema_has_all_20_fields(self):
        assert len(PAGEVIEWS_SCHEMA) == 20

    def test_pageviews_schema_required_modes(self):
        required = {s[0]: s[2] for s in PAGEVIEWS_SCHEMA}
        assert required["event_id"] == "REQUIRED"
        assert required["session_id"] == "REQUIRED"
        assert required["created_at"] == "REQUIRED"
        assert required["url_path"] == "NULLABLE"

    def test_events_schema_has_all_11_fields(self):
        assert len(EVENTS_SCHEMA) == 11

    def test_events_schema_event_data_is_json(self):
        field = next(s for s in EVENTS_SCHEMA if s[0] == "event_data")
        assert field[1] == "JSON"
        assert field[2] == "NULLABLE"

    def test_events_schema_event_name_required(self):
        field = next(s for s in EVENTS_SCHEMA if s[0] == "event_name")
        assert field[2] == "REQUIRED"

    def test_pageviews_schema_field_names_match_query_columns(self):
        """Schema field names should match the columns returned by the SQL query."""
        schema_names = {s[0] for s in PAGEVIEWS_SCHEMA}
        expected = {
            "event_id", "session_id", "visit_id", "created_at",
            "url_path", "url_query", "page_title", "referrer_domain",
            "referrer_path", "hostname", "utm_source", "utm_medium",
            "utm_campaign", "browser", "os", "device", "country",
            "region", "city", "language",
        }
        assert schema_names == expected

    def test_events_schema_field_names_match_query_columns(self):
        schema_names = {s[0] for s in EVENTS_SCHEMA}
        expected = {
            "event_id", "session_id", "created_at", "event_name",
            "url_path", "hostname", "event_data", "browser", "os",
            "device", "country",
        }
        assert schema_names == expected


class TestSerializeRow:
    def test_converts_datetime_to_isoformat(self):
        row = {"created_at": datetime(2026, 3, 1, 10, 0, 0), "name": "test"}
        result = _serialize_row(row)
        assert result["created_at"] == "2026-03-01T10:00:00"
        assert result["name"] == "test"

    def test_converts_event_data_dict_to_json_string(self):
        row = {"event_data": {"article_id": "abc", "origin": "home"}}
        result = _serialize_row(row)
        assert result["event_data"] == '{"article_id": "abc", "origin": "home"}'

    def test_preserves_none_values(self):
        row = {"event_data": None, "url_path": None}
        result = _serialize_row(row)
        assert result["event_data"] is None
        assert result["url_path"] is None

    def test_preserves_string_values(self):
        row = {"url_path": "/artigos/abc123", "browser": "Chrome"}
        result = _serialize_row(row)
        assert result["url_path"] == "/artigos/abc123"


class TestFetchUmamiPageviews:
    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_returns_list_of_dicts(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            {"event_id": "id-1", "session_id": "sess-1", "url_path": "/artigos/abc123",
             "created_at": datetime(2026, 3, 1, 10, 0, 0)},
        ]

        result = fetch_umami_pageviews("postgresql://test", "2026-03-01", "2026-03-02")

        assert len(result) == 1
        assert result[0]["url_path"] == "/artigos/abc123"
        assert result[0]["created_at"] == "2026-03-01T10:00:00"
        mock_conn.close.assert_called_once()

    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_passes_date_params(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        fetch_umami_pageviews("postgresql://test", "2026-03-01", "2026-03-02")

        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert call_args[0][1] == ("2026-03-01", "2026-03-02")

    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_closes_connection_on_error(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            fetch_umami_pageviews("postgresql://test", "2026-03-01", "2026-03-02")

        mock_conn.close.assert_called_once()


class TestFetchUmamiEvents:
    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_serializes_event_data_to_json_string(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            {"event_id": "id-1", "session_id": "sess-1",
             "created_at": datetime(2026, 3, 1, 10, 0, 0),
             "event_name": "article_click", "url_path": "/artigos/abc123",
             "hostname": "example.com", "browser": "chrome", "os": "Mac OS",
             "device": "laptop", "country": "BR",
             "event_data": {"article_id": "abc123", "origin": "home"}},
        ]

        result = fetch_umami_events("postgresql://test", "2026-03-01", "2026-03-02")

        data = json.loads(result[0]["event_data"])
        assert data["article_id"] == "abc123"
        assert data["origin"] == "home"

    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_handles_null_event_data(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = [
            {"event_id": "id-1", "session_id": "sess-1",
             "created_at": datetime(2026, 3, 1, 10, 0, 0),
             "event_name": "button_click", "url_path": "/",
             "hostname": "example.com", "browser": "chrome", "os": "Mac OS",
             "device": "laptop", "country": "BR", "event_data": None},
        ]

        result = fetch_umami_events("postgresql://test", "2026-03-01", "2026-03-02")

        assert result[0]["event_data"] is None

    @patch("data_platform.jobs.bigquery.umami_sync.psycopg2.connect")
    def test_empty_result_returns_empty_list(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        result = fetch_umami_events("postgresql://test", "2026-03-01", "2026-03-02")

        assert result == []


class TestLoadToBigquery:
    def test_empty_list_returns_zero(self):
        result = load_to_bigquery([], "my-project", "dgb_gold.umami_pageviews", PAGEVIEWS_SCHEMA)
        assert result == 0

    def test_loads_rows_to_correct_table(self):
        import sys

        mock_bq = MagicMock()
        mock_client = MagicMock()
        mock_bq.Client.return_value = mock_client
        mock_job = MagicMock()
        mock_job.output_rows = 5
        mock_client.load_table_from_json.return_value = mock_job

        mock_google = MagicMock()
        mock_google_cloud = MagicMock()
        mock_google_cloud.bigquery = mock_bq
        mock_google.cloud = mock_google_cloud

        sys.modules["google"] = mock_google
        sys.modules["google.cloud"] = mock_google_cloud
        sys.modules["google.cloud.bigquery"] = mock_bq
        try:
            rows = [
                {"event_id": "id-1", "session_id": "s-1"},
                {"event_id": "id-2", "session_id": "s-2"},
            ]
            result = load_to_bigquery(rows, "my-project", "dgb_gold.umami_pageviews", PAGEVIEWS_SCHEMA)

            assert result == 5
            call_args = mock_client.load_table_from_json.call_args
            assert call_args[0][1] == "my-project.dgb_gold.umami_pageviews"
        finally:
            sys.modules.pop("google.cloud.bigquery", None)
            sys.modules.pop("google.cloud", None)
            sys.modules.pop("google", None)
