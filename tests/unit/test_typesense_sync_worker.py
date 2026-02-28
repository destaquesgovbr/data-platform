"""
Unit tests for Typesense Sync Worker.

Tests the FastAPI app (Pub/Sub push handling) and the handler
(fetch from PG + upsert to Typesense).
"""

import base64
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from data_platform.workers.typesense_sync.app import app, _pg
from data_platform.workers.typesense_sync.handler import (
    fetch_news_for_typesense,
    upsert_to_typesense,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def pubsub_envelope():
    """Valid Pub/Sub push envelope."""
    data = {"unique_id": "mec-2026-01-01-noticia-1", "agency_key": "mec"}
    return {
        "message": {
            "data": base64.b64encode(json.dumps(data).encode()).decode(),
            "attributes": {"trace_id": "abc-123", "event_version": "1.0"},
            "messageId": "msg-001",
        },
        "subscription": "projects/test/subscriptions/dgb.news.enriched--typesense",
    }


@pytest.fixture
def sample_row_dict():
    """Sample row dict as returned by fetch_news_for_typesense."""
    return {
        "unique_id": "mec-2026-01-01-noticia-1",
        "agency": "mec",
        "title": "Notícia de teste",
        "url": "https://gov.br/mec/noticia-1",
        "image": None,
        "video_url": None,
        "category": "Educação",
        "content": "Conteúdo da notícia",
        "summary": "Resumo gerado por IA",
        "subtitle": None,
        "editorial_lead": None,
        "published_at_ts": 1767265200,  # 2026-01-01 12:00 UTC
        "extracted_at_ts": 1767265800,
        "published_year": 2026,
        "published_month": 1,
        "theme_1_level_1_code": "06",
        "theme_1_level_1_label": "Educação",
        "theme_1_level_2_code": None,
        "theme_1_level_2_label": None,
        "theme_1_level_3_code": None,
        "theme_1_level_3_label": None,
        "most_specific_theme_code": "06",
        "most_specific_theme_label": "Educação",
        "tags": ["educação", "mec"],
        "content_embedding": None,
    }


# =============================================================================
# FastAPI endpoint tests
# =============================================================================


class TestProcessEndpoint:
    """Tests for POST /process Pub/Sub handler."""

    def test_health(self, client):
        """GET /health returns 200."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch("data_platform.workers.typesense_sync.app.upsert_to_typesense", return_value=True)
    @patch("data_platform.workers.typesense_sync.app._get_pg")
    def test_valid_message_returns_200(self, mock_pg, mock_upsert, client, pubsub_envelope):
        """Valid Pub/Sub message triggers upsert and returns 200."""
        resp = client.post("/process", json=pubsub_envelope)
        assert resp.status_code == 200
        mock_upsert.assert_called_once_with("mec-2026-01-01-noticia-1", pg=mock_pg.return_value)

    def test_invalid_json_returns_400(self, client):
        """Non-JSON body returns 400."""
        resp = client.post("/process", content=b"not json", headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_missing_data_returns_400(self, client):
        """Message without data field returns 400."""
        resp = client.post("/process", json={"message": {}})
        assert resp.status_code == 400

    def test_missing_unique_id_returns_400(self, client):
        """Message without unique_id in payload returns 400."""
        data = base64.b64encode(json.dumps({"agency_key": "mec"}).encode()).decode()
        resp = client.post("/process", json={"message": {"data": data}})
        assert resp.status_code == 400

    @patch("data_platform.workers.typesense_sync.app.upsert_to_typesense", return_value=False)
    @patch("data_platform.workers.typesense_sync.app._get_pg")
    def test_upsert_failure_still_returns_200(self, mock_pg, mock_upsert, client, pubsub_envelope):
        """Failed upsert returns 200 to avoid infinite Pub/Sub retries."""
        resp = client.post("/process", json=pubsub_envelope)
        assert resp.status_code == 200


# =============================================================================
# Handler tests
# =============================================================================


class TestFetchNewsForTypesense:
    """Tests for fetch_news_for_typesense."""

    @patch("data_platform.workers.typesense_sync.handler.pd.read_sql_query")
    def test_returns_dict_when_found(self, mock_read_sql, sample_row_dict):
        """Returns dict with Typesense fields when article exists."""
        mock_df = pd.DataFrame([sample_row_dict])
        mock_read_sql.return_value = mock_df

        pg = MagicMock()
        pg._build_typesense_query.return_value = "SELECT ... FROM news n"

        result = fetch_news_for_typesense(pg, "mec-2026-01-01-noticia-1")

        assert result is not None
        assert result["unique_id"] == "mec-2026-01-01-noticia-1"
        assert result["agency"] == "mec"

    @patch("data_platform.workers.typesense_sync.handler.pd.read_sql_query")
    def test_returns_none_when_not_found(self, mock_read_sql):
        """Returns None when article not in PG."""
        mock_read_sql.return_value = pd.DataFrame()

        pg = MagicMock()
        pg._build_typesense_query.return_value = "SELECT ... FROM news n"

        result = fetch_news_for_typesense(pg, "nonexistent")
        assert result is None

    @patch("data_platform.workers.typesense_sync.handler.pd.read_sql_query")
    def test_uses_typesense_query_with_unique_id_filter(self, mock_read_sql):
        """Query appends WHERE n.unique_id = %s."""
        mock_read_sql.return_value = pd.DataFrame()

        pg = MagicMock()
        pg._build_typesense_query.return_value = "SELECT cols FROM news n JOIN themes"

        fetch_news_for_typesense(pg, "test-123")

        call_args = mock_read_sql.call_args
        query = call_args[0][0]
        assert "WHERE n.unique_id = %s" in query
        assert call_args[1]["params"] == ["test-123"]


class TestUpsertToTypesense:
    """Tests for upsert_to_typesense."""

    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_upsert_success(self, mock_fetch, mock_create, mock_get_client, sample_row_dict):
        """Successfully fetches from PG and upserts to Typesense."""
        mock_fetch.return_value = sample_row_dict
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        pg = MagicMock()
        result = upsert_to_typesense("mec-2026-01-01-noticia-1", pg=pg)

        assert result is True
        mock_ts_client.collections["news"].documents.upsert.assert_called_once()

        # Verify the upserted doc has correct id
        doc = mock_ts_client.collections["news"].documents.upsert.call_args[0][0]
        assert doc["id"] == "mec-2026-01-01-noticia-1"
        assert doc["agency"] == "mec"
        assert doc["published_at"] == 1767265200

    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_returns_false_when_not_found(self, mock_fetch):
        """Returns False when article not in PG."""
        mock_fetch.return_value = None

        pg = MagicMock()
        result = upsert_to_typesense("nonexistent", pg=pg)

        assert result is False

    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_returns_false_on_typesense_error(self, mock_fetch, mock_create, mock_get_client, sample_row_dict):
        """Returns False when Typesense upsert fails."""
        mock_fetch.return_value = sample_row_dict
        mock_ts_client = MagicMock()
        mock_ts_client.collections["news"].documents.upsert.side_effect = Exception("Connection refused")
        mock_get_client.return_value = mock_ts_client

        pg = MagicMock()
        result = upsert_to_typesense("mec-2026-01-01-noticia-1", pg=pg)

        assert result is False

    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_calculates_published_week(self, mock_fetch, mock_create, mock_get_client, sample_row_dict):
        """Upserted doc includes calculated published_week."""
        mock_fetch.return_value = sample_row_dict
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        pg = MagicMock()
        upsert_to_typesense("mec-2026-01-01-noticia-1", pg=pg)

        doc = mock_ts_client.collections["news"].documents.upsert.call_args[0][0]
        assert "published_week" in doc
        assert doc["published_week"] > 0

    @patch("data_platform.workers.typesense_sync.handler.PostgresManager")
    @patch("data_platform.workers.typesense_sync.handler.get_client")
    @patch("data_platform.workers.typesense_sync.handler.create_collection")
    @patch("data_platform.workers.typesense_sync.handler.fetch_news_for_typesense")
    def test_creates_pg_when_none(self, mock_fetch, mock_create, mock_get_client, mock_pg_class, sample_row_dict):
        """Creates and closes PostgresManager when not provided."""
        mock_fetch.return_value = sample_row_dict
        mock_get_client.return_value = MagicMock()
        mock_pg_instance = mock_pg_class.return_value

        upsert_to_typesense("test-1", pg=None)

        mock_pg_class.assert_called_once_with(max_connections=2)
        mock_pg_instance.close_all.assert_called_once()
