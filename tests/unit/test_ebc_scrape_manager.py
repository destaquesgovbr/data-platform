"""
Unit tests for EBCScrapeManager URL loading functionality.
"""

import logging
from unittest.mock import Mock, mock_open, patch

import pytest
import yaml  # type: ignore[import-untyped]

from data_platform.scrapers.ebc_scrape_manager import EBCScrapeManager


class TestLoadUrlsFromYaml:
    """Tests for _load_urls_from_yaml method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def ebc_scrape_manager(self) -> EBCScrapeManager:
        """Create EBCScrapeManager with mock storage."""
        return EBCScrapeManager(storage=Mock())

    # --- Loading URLs Tests ---

    def test_load_all_urls(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test loading all URLs from YAML."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas",
                    "active": True,
                },
                "memoria_ebc": {"url": "https://memoria.ebc.com.br/noticias", "active": True},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml")

        assert len(urls) == 2
        assert "https://agenciabrasil.ebc.com.br/ultimas" in urls
        assert "https://memoria.ebc.com.br/noticias" in urls

    def test_load_single_source(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test loading single source URL."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas",
                    "active": True,
                },
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml", source="agencia_brasil")

        assert urls == ["https://agenciabrasil.ebc.com.br/ultimas"]

    def test_load_all_urls_filters_inactive(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test that inactive sources are filtered out."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas",
                    "active": True,
                },
                "memoria_ebc": {"url": "https://memoria.ebc.com.br/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml")

        assert len(urls) == 1
        assert "https://agenciabrasil.ebc.com.br/ultimas" in urls
        assert "https://memoria.ebc.com.br/noticias" not in urls

    def test_active_defaults_to_true_when_missing(
        self, ebc_scrape_manager: EBCScrapeManager
    ) -> None:
        """Test that missing 'active' field defaults to True."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas"
                },  # no 'active' key
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml")

        assert len(urls) == 1

    # --- Single Source Lookup Tests ---

    def test_load_single_inactive_source_raises_error(
        self, ebc_scrape_manager: EBCScrapeManager
    ) -> None:
        """Test that requesting an inactive source raises ValueError."""
        yaml_content = {
            "sources": {
                "memoria_ebc": {"url": "https://memoria.ebc.com.br/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with pytest.raises(ValueError, match="Source 'memoria_ebc' is inactive"):
                ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml", source="memoria_ebc")

    def test_load_nonexistent_source_raises_error(
        self, ebc_scrape_manager: EBCScrapeManager
    ) -> None:
        """Test that requesting unknown source raises ValueError."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas",
                    "active": True,
                }
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with pytest.raises(ValueError, match="not found"):
                ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml", source="unknown")

    # --- Logging Tests ---

    def test_logs_filtered_sources(
        self, ebc_scrape_manager: EBCScrapeManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that filtered sources are logged."""
        yaml_content = {
            "sources": {
                "agencia_brasil": {
                    "url": "https://agenciabrasil.ebc.com.br/ultimas",
                    "active": True,
                },
                "memoria_ebc": {"url": "https://memoria.ebc.com.br/noticias", "active": False},
                "tvbrasil": {"url": "https://tvbrasil.ebc.com.br/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with caplog.at_level(logging.INFO):
                ebc_scrape_manager._load_urls_from_yaml("ebc_urls.yaml")

        assert "Filtered 2 inactive sources" in caplog.text
        assert "memoria_ebc" in caplog.text
        assert "tvbrasil" in caplog.text


class TestExtractUrl:
    """Tests for _extract_url helper method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def ebc_scrape_manager(self) -> EBCScrapeManager:
        return EBCScrapeManager(storage=Mock())

    def test_extract_url_from_dict(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test extracting URL from dict format."""
        result = ebc_scrape_manager._extract_url({"url": "https://example.com", "active": True})
        assert result == "https://example.com"

    def test_extract_url_from_dict_without_active(
        self, ebc_scrape_manager: EBCScrapeManager
    ) -> None:
        """Test extracting URL from dict without active field."""
        result = ebc_scrape_manager._extract_url({"url": "https://example.com"})
        assert result == "https://example.com"


class TestIsSourceInactive:
    """Tests for _is_source_inactive helper method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def ebc_scrape_manager(self) -> EBCScrapeManager:
        return EBCScrapeManager(storage=Mock())

    def test_active_true_is_not_inactive(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test that active=True returns False (not inactive)."""
        data = {"url": "https://example.com", "active": True}
        assert ebc_scrape_manager._is_source_inactive("agencia_brasil", data) is False

    def test_active_false_is_inactive(self, ebc_scrape_manager: EBCScrapeManager) -> None:
        """Test that active=False returns True (is inactive)."""
        data = {"url": "https://example.com", "active": False}
        assert ebc_scrape_manager._is_source_inactive("memoria_ebc", data) is True

    def test_missing_active_defaults_to_not_inactive(
        self, ebc_scrape_manager: EBCScrapeManager
    ) -> None:
        """Test that missing active field defaults to active (not inactive)."""
        data = {"url": "https://example.com"}
        assert ebc_scrape_manager._is_source_inactive("agencia_brasil", data) is False
