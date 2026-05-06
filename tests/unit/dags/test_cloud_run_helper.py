"""Unit tests for the Cloud Run authentication helper."""

from unittest.mock import Mock, patch

from data_platform.cloud_run import get_id_token, post


class TestGetIdToken:
    @patch("data_platform.cloud_run.google.oauth2.id_token.fetch_id_token")
    @patch("data_platform.cloud_run.google.auth.transport.requests.Request")
    def test_fetches_token_for_audience(self, mock_request_cls, mock_fetch) -> None:
        mock_fetch.return_value = "test-token"
        token = get_id_token("https://my-service.run.app")
        mock_fetch.assert_called_once_with(mock_request_cls.return_value, "https://my-service.run.app")
        assert token == "test-token"


class TestPost:
    @patch("data_platform.cloud_run.requests.post")
    @patch("data_platform.cloud_run.get_id_token")
    def test_sends_auth_header(self, mock_get_token, mock_post) -> None:
        mock_get_token.return_value = "id-token-123"
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())

        resp = post("https://svc.run.app/endpoint", json={"key": "val"}, timeout=30)

        mock_get_token.assert_called_once_with("https://svc.run.app")
        mock_post.assert_called_once_with(
            "https://svc.run.app/endpoint",
            json={"key": "val"},
            headers={"Authorization": "Bearer id-token-123"},
            timeout=30,
        )
        assert resp.status_code == 200

    @patch("data_platform.cloud_run.requests.post")
    @patch("data_platform.cloud_run.get_id_token")
    def test_extracts_audience_from_url_with_path(self, mock_get_token, mock_post) -> None:
        mock_get_token.return_value = "tok"
        mock_post.return_value = Mock(raise_for_status=Mock())

        post("https://my-service-abc123.a.run.app/verify/integrity", json={}, timeout=10)

        mock_get_token.assert_called_once_with("https://my-service-abc123.a.run.app")
