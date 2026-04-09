"""Unit tests for thumbnail worker FastAPI app."""

import base64
import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient


def _make_pubsub_envelope(unique_id: str) -> dict:
    """Create a Pub/Sub push message envelope."""
    data = base64.b64encode(json.dumps({"unique_id": unique_id}).encode()).decode()
    return {"message": {"data": data, "attributes": {}}}


@pytest.fixture()
def _mock_pg():
    """Mock PostgresManager so lifespan doesn't connect to a real DB."""
    with patch("data_platform.workers.thumbnail_worker.app.PostgresManager") as MockPG:
        mock_pg = Mock()
        MockPG.return_value = mock_pg
        yield mock_pg


class TestHealthEndpoint:
    """Tests for GET /health."""

    @pytest.mark.usefixtures("_mock_pg")
    def test_returns_200(self) -> None:
        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestLifespan:
    """Tests for FastAPI lifespan (PG connection management)."""

    def test_lifespan_closes_pg_on_shutdown(self) -> None:
        """close_all is called when the app shuts down."""
        with patch("data_platform.workers.thumbnail_worker.app.PostgresManager") as MockPG:
            mock_pg = Mock()
            MockPG.return_value = mock_pg

            from data_platform.workers.thumbnail_worker.app import app

            with TestClient(app):
                pass  # triggers startup + shutdown

        mock_pg.close_all.assert_called_once()


class TestProcessEndpoint:
    """Tests for POST /process."""

    @pytest.mark.usefixtures("_mock_pg")
    @patch("data_platform.workers.thumbnail_worker.app.handle_thumbnail_generation")
    def test_decodes_pubsub_envelope(self, mock_handler) -> None:
        mock_handler.return_value = {"status": "generated"}

        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.post("/process", json=_make_pubsub_envelope("uid_123"))

        assert resp.status_code == 200
        mock_handler.assert_called_once()
        args = mock_handler.call_args[0]
        assert args[0] == "uid_123"

    @pytest.mark.usefixtures("_mock_pg")
    def test_returns_400_for_invalid_json(self) -> None:
        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.post(
                "/process", content=b"not json", headers={"content-type": "application/json"}
            )
        assert resp.status_code == 400

    @pytest.mark.usefixtures("_mock_pg")
    def test_returns_400_for_missing_data(self) -> None:
        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.post("/process", json={"message": {}})
        assert resp.status_code == 400

    @pytest.mark.usefixtures("_mock_pg")
    def test_returns_400_for_missing_unique_id(self) -> None:
        data = base64.b64encode(json.dumps({"foo": "bar"}).encode()).decode()

        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.post("/process", json={"message": {"data": data}})
        assert resp.status_code == 400

    @pytest.mark.usefixtures("_mock_pg")
    @patch("data_platform.workers.thumbnail_worker.app.handle_thumbnail_generation")
    def test_returns_json_content_type(self, mock_handler) -> None:
        mock_handler.return_value = {"status": "generated"}

        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app) as client:
            resp = client.post("/process", json=_make_pubsub_envelope("uid_123"))

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json() == {"status": "generated"}

    @pytest.mark.usefixtures("_mock_pg")
    @patch("data_platform.workers.thumbnail_worker.app.handle_thumbnail_generation")
    def test_returns_200_ack_on_unhandled_error(self, mock_handler) -> None:
        """Unhandled errors return 200 to ACK the Pub/Sub message (avoid infinite retry)."""
        mock_handler.side_effect = RuntimeError("DB connection lost")

        from data_platform.workers.thumbnail_worker.app import app

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/process", json=_make_pubsub_envelope("uid_123"))

        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "DB connection" not in resp.text  # No leak
