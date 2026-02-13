"""
Integration tests for EBC scraper using live URLs.

These tests hit real EBC websites to validate that:
1. HTML structure hasn't changed
2. editorial_lead is correctly extracted from TV Brasil
3. Agencia Brasil correctly has no editorial_lead

Run with:
    pytest tests/integration/test_ebc_scraper_live.py -v -m integration

Note: These tests require network access and may be slow.
"""

import pytest
import requests

from data_platform.scrapers.ebc_webscraper import EBCWebScraper

# =============================================================================
# Configuration
# =============================================================================

# URLs conhecidas para teste (artigos que provavelmente permanecerão no ar)
# TV Brasil - programs with editorial_lead (program name)
TVBRASIL_TEST_URLS = [
    # Caminhos da Reportagem
    "https://tvbrasil.ebc.com.br/caminhos-da-reportagem/2026/01/foz-do-iguacu-crimes-na-fronteira-mais-movimentada-do-brasil",
    "https://tvbrasil.ebc.com.br/caminhos-da-reportagem/2025/12/100-vezes-sao-silvestre",
    "https://tvbrasil.ebc.com.br/caminhos-da-reportagem/2025/12/o-brega-e-pop",
]

# Agência Brasil - news articles without editorial_lead
AGENCIABRASIL_TEST_URLS = [
    "https://agenciabrasil.ebc.com.br/economia/noticia/2026-02/mais-da-metade-dos-negocios-em-favelas-foi-aberta-partir-da-pandemia",
    "https://agenciabrasil.ebc.com.br/economia/noticia/2026-02/conab-preve-colheita-recorde-de-cafe-com-crescimento-de-171-em-2026",
    "https://agenciabrasil.ebc.com.br/politica/noticia/2026-02/quebra-do-sigilo-do-banco-master-sai-da-pauta-da-cpmi-do-inss",
]


# =============================================================================
# Helper Functions
# =============================================================================


def find_working_url(urls: list[str], timeout: int = 10) -> str | None:
    """
    Find first URL that returns 200 status.

    Args:
        urls: List of URLs to try
        timeout: Request timeout in seconds

    Returns:
        First working URL or None if all fail
    """
    for url in urls:
        try:
            response = requests.head(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 200:
                return url
        except requests.RequestException:
            continue
    return None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def ebc_scraper() -> EBCWebScraper:
    """EBCWebScraper instance for integration testing."""
    return EBCWebScraper(min_date="2020-01-01", base_url="https://agenciabrasil.ebc.com.br/ultimas")


@pytest.fixture(scope="module")
def network_available() -> bool:
    """Check if network is available."""
    try:
        requests.head("https://tvbrasil.ebc.com.br", timeout=5)
        return True
    except requests.RequestException:
        return False


@pytest.fixture(scope="module")
def tvbrasil_url(network_available: bool) -> str | None:
    """Find a working TV Brasil URL."""
    if not network_available:
        return None
    return find_working_url(TVBRASIL_TEST_URLS)


@pytest.fixture(scope="module")
def agenciabrasil_url(network_available: bool) -> str | None:
    """Find a working Agencia Brasil URL."""
    if not network_available:
        return None
    return find_working_url(AGENCIABRASIL_TEST_URLS)


# =============================================================================
# Tests - TV Brasil
# =============================================================================


@pytest.mark.integration
class TestTVBrasilLive:
    """Integration tests for TV Brasil scraping."""

    def test_tvbrasil_page_structure_unchanged(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        tvbrasil_url: str | None,
    ) -> None:
        """Verify TV Brasil HTML structure hasn't changed."""
        if not network_available:
            pytest.skip("Network not available")
        if not tvbrasil_url:
            pytest.skip("No working TV Brasil URL found")

        result = ebc_scraper.scrape_news_page(tvbrasil_url)

        # Validações estruturais básicas
        assert result.get("title"), "Title not found - HTML structure may have changed"
        assert not result.get("error"), f"Scraper error: {result.get('error')}"

    def test_tvbrasil_extracts_editorial_lead(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        tvbrasil_url: str | None,
    ) -> None:
        """Verify editorial_lead is extracted from TV Brasil."""
        if not network_available:
            pytest.skip("Network not available")
        if not tvbrasil_url:
            pytest.skip("No working TV Brasil URL found")

        result = ebc_scraper.scrape_news_page(tvbrasil_url)

        # Editorial lead deve existir para TV Brasil (nome do programa)
        assert result.get("editorial_lead"), (
            "editorial_lead not found - "
            "HTML structure may have changed or <h4 class='txtNoticias'> not present"
        )

    def test_tvbrasil_source_is_empty(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        tvbrasil_url: str | None,
    ) -> None:
        """Verify source field is empty for TV Brasil."""
        if not network_available:
            pytest.skip("Network not available")
        if not tvbrasil_url:
            pytest.skip("No working TV Brasil URL found")

        result = ebc_scraper.scrape_news_page(tvbrasil_url)

        # Source deve estar vazio para TV Brasil
        assert result.get("source") == "", (
            f"source should be empty for TV Brasil, got: {result.get('source')}"
        )

    def test_tvbrasil_extracts_content(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        tvbrasil_url: str | None,
    ) -> None:
        """Verify content is extracted from TV Brasil."""
        if not network_available:
            pytest.skip("Network not available")
        if not tvbrasil_url:
            pytest.skip("No working TV Brasil URL found")

        result = ebc_scraper.scrape_news_page(tvbrasil_url)

        # Deve ter conteúdo
        assert result.get("content"), "Content not found - HTML structure may have changed"
        assert len(result.get("content", "")) > 50, "Content too short"


# =============================================================================
# Tests - Agencia Brasil
# =============================================================================


@pytest.mark.integration
class TestAgenciaBrasilLive:
    """Integration tests for Agencia Brasil scraping."""

    def test_agenciabrasil_page_structure_unchanged(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        agenciabrasil_url: str | None,
    ) -> None:
        """Verify Agencia Brasil HTML structure hasn't changed."""
        if not network_available:
            pytest.skip("Network not available")
        if not agenciabrasil_url:
            pytest.skip("No working Agencia Brasil URL found")

        result = ebc_scraper.scrape_news_page(agenciabrasil_url)

        # Validações estruturais básicas
        assert result.get("title"), "Title not found - HTML structure may have changed"
        assert not result.get("error"), f"Scraper error: {result.get('error')}"

    def test_agenciabrasil_no_editorial_lead(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        agenciabrasil_url: str | None,
    ) -> None:
        """Verify Agencia Brasil has no editorial_lead."""
        if not network_available:
            pytest.skip("Network not available")
        if not agenciabrasil_url:
            pytest.skip("No working Agencia Brasil URL found")

        result = ebc_scraper.scrape_news_page(agenciabrasil_url)

        # Agencia Brasil NÃO deve ter editorial_lead
        assert result.get("editorial_lead") == "", (
            f"Agencia Brasil should not have editorial_lead, got: {result.get('editorial_lead')}"
        )

    def test_agenciabrasil_has_source(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        agenciabrasil_url: str | None,
    ) -> None:
        """Verify Agencia Brasil has source/author field."""
        if not network_available:
            pytest.skip("Network not available")
        if not agenciabrasil_url:
            pytest.skip("No working Agencia Brasil URL found")

        result = ebc_scraper.scrape_news_page(agenciabrasil_url)

        # Agencia Brasil deve ter source (autor)
        assert result.get("source"), (
            "source not found for Agencia Brasil - HTML structure may have changed"
        )

    def test_agenciabrasil_extracts_content(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        agenciabrasil_url: str | None,
    ) -> None:
        """Verify content is extracted from Agencia Brasil."""
        if not network_available:
            pytest.skip("Network not available")
        if not agenciabrasil_url:
            pytest.skip("No working Agencia Brasil URL found")

        result = ebc_scraper.scrape_news_page(agenciabrasil_url)

        # Deve ter conteúdo
        assert result.get("content"), "Content not found - HTML structure may have changed"
        assert len(result.get("content", "")) > 50, "Content too short"

    def test_agenciabrasil_extracts_published_datetime(
        self,
        ebc_scraper: EBCWebScraper,
        network_available: bool,
        agenciabrasil_url: str | None,
    ) -> None:
        """Verify published_datetime is extracted from Agencia Brasil."""
        if not network_available:
            pytest.skip("Network not available")
        if not agenciabrasil_url:
            pytest.skip("No working Agencia Brasil URL found")

        result = ebc_scraper.scrape_news_page(agenciabrasil_url)

        # Deve ter data de publicação
        assert result.get("published_datetime"), (
            "published_datetime not found - HTML structure may have changed"
        )
