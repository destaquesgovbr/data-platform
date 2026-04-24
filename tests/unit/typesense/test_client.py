"""
Unit tests for Typesense client (connection and configuration).
"""

import json
from unittest.mock import Mock, patch

import pytest

from data_platform.typesense.client import (
    get_client,
    wait_for_typesense,
    _parse_write_conn,
)


class TestParseWriteConn:
    """Tests for _parse_write_conn helper."""

    @patch.dict(
        "os.environ",
        {
            "TYPESENSE_WRITE_CONN": '{"host": "ts.com", "port": "443", "apiKey": "key123", "protocol": "https"}'
        },
    )
    def test_parse_valid_json(self):
        """Parse valid TYPESENSE_WRITE_CONN JSON."""
        host, port, key, protocol = _parse_write_conn()
        assert host == "ts.com"
        assert port == "443"
        assert key == "key123"
        assert protocol == "https"

    @patch.dict("os.environ", {}, clear=True)
    def test_parse_empty_returns_defaults(self):
        """Empty env var returns None values."""
        host, port, key, protocol = _parse_write_conn()
        assert host is None
        assert port is None
        assert key is None
        assert protocol == "http"

    @patch.dict("os.environ", {"TYPESENSE_WRITE_CONN": "invalid json"})
    def test_parse_invalid_json_returns_defaults(self):
        """Invalid JSON returns default values."""
        host, port, key, protocol = _parse_write_conn()
        assert host is None


class TestGetClient:
    """Tests for get_client() function."""

    @patch("data_platform.typesense.client.typesense.Client")
    def test_get_client_with_explicit_params(self, mock_client_class):
        """Create client with explicit parameters."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        client = get_client(
            host="ts.example.com", port="8108", api_key="test_key", protocol="https"
        )

        assert client == mock_client
        config = mock_client_class.call_args[0][0]
        assert config["nodes"][0]["host"] == "ts.example.com"
        assert config["nodes"][0]["port"] == "8108"
        assert config["nodes"][0]["protocol"] == "https"
        assert config["api_key"] == "test_key"

    @patch("data_platform.typesense.client.typesense.Client")
    @patch.dict(
        "os.environ",
        {
            "TYPESENSE_HOST": "localhost",
            "TYPESENSE_PORT": "8108",
            "TYPESENSE_API_KEY": "env_key",
        },
    )
    def test_get_client_from_env(self, mock_client_class):
        """Create client from environment variables."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        client = get_client()

        config = mock_client_class.call_args[0][0]
        assert config["nodes"][0]["host"] == "localhost"
        assert config["api_key"] == "env_key"

    @patch("data_platform.typesense.client.typesense.Client")
    def test_get_client_custom_timeout(self, mock_client_class):
        """Create client with custom timeout."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        get_client(api_key="key", timeout=30)

        config = mock_client_class.call_args[0][0]
        assert config["connection_timeout_seconds"] == 30

    @patch("data_platform.typesense.client.typesense.Client")
    @patch("data_platform.typesense.client._parse_write_conn")
    def test_get_client_prefers_write_conn_over_env(
        self, mock_parse, mock_client_class
    ):
        """TYPESENSE_WRITE_CONN takes precedence over individual env vars."""
        mock_parse.return_value = ("write.host", "443", "write_key", "https")
        mock_client_class.return_value = Mock()

        with patch.dict(
            "os.environ",
            {"TYPESENSE_HOST": "env.host", "TYPESENSE_API_KEY": "env_key"},
        ):
            get_client()

        config = mock_client_class.call_args[0][0]
        assert config["nodes"][0]["host"] == "write.host"
        assert config["api_key"] == "write_key"


class TestWaitForTypesense:
    """Tests for wait_for_typesense() function."""

    @patch("data_platform.typesense.client.requests.get")
    @patch("data_platform.typesense.client.get_client")
    def test_wait_success_on_first_try(self, mock_get_client, mock_requests_get):
        """Wait succeeds immediately when Typesense is ready."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        result = wait_for_typesense(api_key="key", max_retries=3)

        assert result == mock_client
        assert mock_requests_get.call_count == 1

    @patch("data_platform.typesense.client.requests.get")
    @patch("data_platform.typesense.client.get_client")
    @patch("data_platform.typesense.client.time.sleep")
    def test_wait_retries_on_connection_error(
        self, mock_sleep, mock_get_client, mock_requests_get
    ):
        """Wait retries on connection errors."""
        # First 2 calls fail, third succeeds
        mock_requests_get.side_effect = [
            ConnectionError("Refused"),
            ConnectionError("Refused"),
            Mock(status_code=200),
        ]

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        result = wait_for_typesense(api_key="key", max_retries=3, retry_interval=1)

        assert result == mock_client
        assert mock_requests_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("data_platform.typesense.client.requests.get")
    def test_wait_returns_none_on_timeout(self, mock_requests_get):
        """Wait returns None after max retries."""
        mock_requests_get.side_effect = ConnectionError("Refused")

        result = wait_for_typesense(api_key="key", max_retries=2, retry_interval=0)

        assert result is None
        assert mock_requests_get.call_count == 2
