"""Unit tests for thumbnail worker FastAPI app."""

import base64
import json
from unittest.mock import Mock, patch

from data_platform.workers.thumbnail_worker.app import app
from fastapi.testclient import TestClient


def _make_pubsub_envelope(unique_id: str) -> dict:
    """Create a Pub/Sub push message envelope."""
    data = base64.b64encode(json.dumps({"unique_id": unique_id}).encode()).decode()
    return {"message": {"data": data, "attributes": {}}}


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_returns_200(self) -> None:
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestProcessEndpoint:
    """Tests for POST /process."""

    @patch("data_platform.workers.thumbnail_worker.app.handle_thumbnail_generation")
    @patch("data_platform.workers.thumbnail_worker.app._get_pg")
    def test_decodes_pubsub_envelope(self, mock_get_pg, mock_handler) -> None:
        mock_handler.return_value = {"status": "generated"}
        mock_get_pg.return_value = Mock()

        client = TestClient(app)
        resp = client.post("/process", json=_make_pubsub_envelope("uid_123"))

        assert resp.status_code == 200
        mock_handler.assert_called_once()
        args = mock_handler.call_args[0]
        assert args[0] == "uid_123"

    def test_returns_400_for_invalid_json(self) -> None:
        client = TestClient(app)
        resp = client.post(
            "/process", content=b"not json", headers={"content-type": "application/json"}
        )
        assert resp.status_code == 400

    def test_returns_400_for_missing_data(self) -> None:
        client = TestClient(app)
        resp = client.post("/process", json={"message": {}})
        assert resp.status_code == 400

    def test_returns_400_for_missing_unique_id(self) -> None:
        data = base64.b64encode(json.dumps({"foo": "bar"}).encode()).decode()
        client = TestClient(app)
        resp = client.post("/process", json={"message": {"data": data}})
        assert resp.status_code == 400
