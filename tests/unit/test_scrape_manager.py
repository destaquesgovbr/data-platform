"""
Unit tests for ScrapeManager URL loading functionality.
"""

import logging
from unittest.mock import Mock, mock_open, patch

import pytest
import yaml  # type: ignore[import-untyped]

from data_platform.scrapers.scrape_manager import ScrapeManager


class TestLoadUrlsFromYaml:
    """Tests for _load_urls_from_yaml method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def scrape_manager(self) -> ScrapeManager:
        """Create ScrapeManager with mock storage."""
        return ScrapeManager(storage=Mock())

    # --- Legacy Format Tests ---

    def test_load_all_urls_legacy_format(self, scrape_manager: ScrapeManager) -> None:
        """Test loading all URLs from legacy string format."""
        yaml_content = {
            "agencies": {
                "abc": "https://www.gov.br/abc/noticias",
                "mec": "https://www.gov.br/mec/noticias",
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert len(urls) == 2
        assert "https://www.gov.br/abc/noticias" in urls
        assert "https://www.gov.br/mec/noticias" in urls

    def test_load_single_agency_legacy_format(self, scrape_manager: ScrapeManager) -> None:
        """Test loading single agency URL from legacy format."""
        yaml_content = {
            "agencies": {
                "abc": "https://www.gov.br/abc/noticias",
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml", agency="abc")

        assert urls == ["https://www.gov.br/abc/noticias"]

    # --- New Format Tests ---

    def test_load_all_urls_new_format_all_active(self, scrape_manager: ScrapeManager) -> None:
        """Test loading URLs when all agencies are active."""
        yaml_content = {
            "agencies": {
                "abc": {"url": "https://www.gov.br/abc/noticias", "active": True},
                "mec": {"url": "https://www.gov.br/mec/noticias", "active": True},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert len(urls) == 2

    def test_load_all_urls_filters_inactive(self, scrape_manager: ScrapeManager) -> None:
        """Test that inactive agencies are filtered out."""
        yaml_content = {
            "agencies": {
                "abc": {"url": "https://www.gov.br/abc/noticias", "active": True},
                "cisc": {"url": "https://www.gov.br/cisc/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert len(urls) == 1
        assert "https://www.gov.br/abc/noticias" in urls
        assert "https://www.gov.br/cisc/noticias" not in urls

    def test_active_defaults_to_true_when_missing(self, scrape_manager: ScrapeManager) -> None:
        """Test that missing 'active' field defaults to True."""
        yaml_content = {
            "agencies": {
                "abc": {"url": "https://www.gov.br/abc/noticias"},  # no 'active' key
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert len(urls) == 1

    # --- Mixed Format Tests ---

    def test_load_mixed_format(self, scrape_manager: ScrapeManager) -> None:
        """Test loading from file with both legacy and new formats."""
        yaml_content = {
            "agencies": {
                "abc": "https://www.gov.br/abc/noticias",  # legacy
                "mec": {
                    "url": "https://www.gov.br/mec/noticias",
                    "active": True,
                },  # new
                "cisc": {
                    "url": "https://www.gov.br/cisc/noticias",
                    "active": False,
                },  # inactive
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            urls = scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert len(urls) == 2
        assert "https://www.gov.br/abc/noticias" in urls
        assert "https://www.gov.br/mec/noticias" in urls

    # --- Single Agency Lookup Tests ---

    def test_load_single_inactive_agency_raises_error(self, scrape_manager: ScrapeManager) -> None:
        """Test that requesting an inactive agency raises ValueError."""
        yaml_content = {
            "agencies": {
                "cisc": {"url": "https://www.gov.br/cisc/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with pytest.raises(ValueError, match="Agency 'cisc' is inactive"):
                scrape_manager._load_urls_from_yaml("site_urls.yaml", agency="cisc")

    def test_load_nonexistent_agency_raises_error(self, scrape_manager: ScrapeManager) -> None:
        """Test that requesting unknown agency raises ValueError."""
        yaml_content = {"agencies": {"abc": "https://www.gov.br/abc/noticias"}}
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with pytest.raises(ValueError, match="not found"):
                scrape_manager._load_urls_from_yaml("site_urls.yaml", agency="unknown")

    # --- Logging Tests ---

    def test_logs_filtered_agencies(
        self, scrape_manager: ScrapeManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that filtered agencies are logged."""
        yaml_content = {
            "agencies": {
                "abc": {"url": "https://www.gov.br/abc/noticias", "active": True},
                "cisc": {"url": "https://www.gov.br/cisc/noticias", "active": False},
                "ibde": {"url": "https://www.gov.br/ibde/noticias", "active": False},
            }
        }
        with patch("builtins.open", mock_open(read_data=yaml.dump(yaml_content))):
            with caplog.at_level(logging.INFO):
                scrape_manager._load_urls_from_yaml("site_urls.yaml")

        assert "Filtered 2 inactive agencies" in caplog.text
        assert "cisc" in caplog.text
        assert "ibde" in caplog.text


class TestExtractUrl:
    """Tests for _extract_url helper method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def scrape_manager(self) -> ScrapeManager:
        return ScrapeManager(storage=Mock())

    def test_extract_url_from_string(self, scrape_manager: ScrapeManager) -> None:
        """Test extracting URL from legacy string format."""
        result = scrape_manager._extract_url("https://example.com")
        assert result == "https://example.com"

    def test_extract_url_from_dict(self, scrape_manager: ScrapeManager) -> None:
        """Test extracting URL from new dict format."""
        result = scrape_manager._extract_url({"url": "https://example.com", "active": True})
        assert result == "https://example.com"


class TestIsAgencyInactive:
    """Tests for _is_agency_inactive helper method."""

    @pytest.fixture  # type: ignore[untyped-decorator]
    def scrape_manager(self) -> ScrapeManager:
        return ScrapeManager(storage=Mock())

    def test_legacy_format_is_always_active(self, scrape_manager: ScrapeManager) -> None:
        """Test that legacy string format is always considered active."""
        assert scrape_manager._is_agency_inactive("abc", "https://example.com") is False

    def test_active_true_is_not_inactive(self, scrape_manager: ScrapeManager) -> None:
        """Test that active=True returns False (not inactive)."""
        data = {"url": "https://example.com", "active": True}
        assert scrape_manager._is_agency_inactive("abc", data) is False

    def test_active_false_is_inactive(self, scrape_manager: ScrapeManager) -> None:
        """Test that active=False returns True (is inactive)."""
        data = {"url": "https://example.com", "active": False}
        assert scrape_manager._is_agency_inactive("abc", data) is True

    def test_missing_active_defaults_to_not_inactive(self, scrape_manager: ScrapeManager) -> None:
        """Test that missing active field defaults to active (not inactive)."""
        data = {"url": "https://example.com"}
        assert scrape_manager._is_agency_inactive("abc", data) is False
