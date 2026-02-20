"""
Testes para validação de URLs duplicadas em configurações de scrapers.

Estes testes garantem que:
1. A função de busca de duplicatas identifica corretamente URLs duplicadas
2. A normalização de URLs funciona adequadamente (trailing slash, case-insensitive)
3. Entradas comentadas (valor None) são ignoradas
4. A validação gera mensagens de erro descritivas
5. O arquivo de produção site_urls.yaml está livre de duplicatas
"""

from pathlib import Path

import pytest

from data_platform.scrapers.config.validators import (
    _extract_url,
    find_duplicate_urls,
    load_site_urls_config,
    normalize_url,
    validate_agencies_config,
    validate_no_duplicate_urls,
)


class TestNormalizeUrl:
    """Testes para normalização de URLs."""

    def test_remove_trailing_slash(self):
        """Remove trailing slash da URL."""
        assert normalize_url("https://example.com/") == "https://example.com"
        assert normalize_url("https://example.com/path/") == "https://example.com/path"

    def test_convert_to_lowercase(self):
        """Converte URL para lowercase."""
        assert normalize_url("https://EXAMPLE.com/Path") == "https://example.com/path"

    def test_both_normalizations(self):
        """Aplica ambas normalizações."""
        assert normalize_url("https://EXAMPLE.com/Path/") == "https://example.com/path"

    def test_already_normalized(self):
        """URL já normalizada permanece inalterada."""
        url = "https://example.com/path"
        assert normalize_url(url) == url


class TestFindDuplicateUrls:
    """Testes para função de busca de URLs duplicadas."""

    def test_no_duplicates(self):
        """Config sem duplicatas retorna lista vazia."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": "https://example.com/b",
            "agency3": "https://example.com/c",
        }
        assert find_duplicate_urls(config) == []

    def test_one_duplicate(self):
        """Detecta uma URL duplicada."""
        config = {
            "agency1": "https://example.com/same",
            "agency2": "https://example.com/different",
            "agency3": "https://example.com/same",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 1
        url, agencies = duplicates[0]
        assert url == "https://example.com/same"
        assert set(agencies) == {"agency1", "agency3"}

    def test_multiple_duplicates(self):
        """Detecta múltiplas URLs duplicadas."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": "https://example.com/a",
            "agency3": "https://example.com/b",
            "agency4": "https://example.com/b",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 2
        urls = {url for url, _ in duplicates}
        assert urls == {"https://example.com/a", "https://example.com/b"}

    def test_trailing_slash_detected_as_duplicate(self):
        """URLs com/sem trailing slash são detectadas como duplicatas."""
        config = {
            "agency1": "https://example.com/path",
            "agency2": "https://example.com/path/",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 1

    def test_case_insensitive_duplicate(self):
        """Comparação case-insensitive detecta duplicatas."""
        config = {
            "agency1": "https://example.com/Path",
            "agency2": "https://example.com/path",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 1

    def test_none_values_ignored(self):
        """Valores None (comentados) são ignorados."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": None,
            "agency3": "https://example.com/b",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 0

    def test_empty_string_ignored(self):
        """Strings vazias são ignoradas."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": "",
            "agency3": "https://example.com/b",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 0

    def test_three_agencies_same_url(self):
        """Três ou mais agências usando mesma URL."""
        config = {
            "agency1": "https://example.com/same",
            "agency2": "https://example.com/same",
            "agency3": "https://example.com/same",
        }
        duplicates = find_duplicate_urls(config)
        assert len(duplicates) == 1
        _, agencies = duplicates[0]
        assert len(agencies) == 3


class TestValidateNoDuplicateUrls:
    """Testes para função de validação de URLs duplicadas."""

    def test_valid_config_returns_empty_list(self):
        """Config válida sem duplicatas retorna lista vazia."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": "https://example.com/b",
        }
        errors = validate_no_duplicate_urls(config)
        assert errors == []

    def test_duplicate_returns_error_message(self):
        """Config com duplicata retorna mensagem de erro."""
        config = {
            "agency1": "https://example.com/same",
            "agency2": "https://example.com/same",
        }
        errors = validate_no_duplicate_urls(config)
        assert len(errors) == 1
        assert "URL duplicada encontrada" in errors[0]
        assert "agency1" in errors[0]
        assert "agency2" in errors[0]

    def test_multiple_duplicates_returns_multiple_errors(self):
        """Múltiplas duplicatas retornam múltiplos erros."""
        config = {
            "agency1": "https://example.com/a",
            "agency2": "https://example.com/a",
            "agency3": "https://example.com/b",
            "agency4": "https://example.com/b",
        }
        errors = validate_no_duplicate_urls(config)
        assert len(errors) == 2

    def test_error_message_includes_agency_count(self):
        """Mensagem de erro inclui contagem de agências."""
        config = {
            "agency1": "https://example.com/same",
            "agency2": "https://example.com/same",
            "agency3": "https://example.com/same",
        }
        errors = validate_no_duplicate_urls(config)
        assert "3 agências" in errors[0]


class TestLoadSiteUrlsConfig:
    """Testes para carregamento de configuração."""

    def test_load_default_config(self):
        """Carrega configuração do caminho padrão."""
        # Este teste usa o arquivo de produção
        config = load_site_urls_config()
        assert isinstance(config, dict)
        assert len(config) > 0

    def test_config_has_expected_structure(self):
        """Config carregada tem estrutura esperada."""
        config = load_site_urls_config()
        # Verifica que tem algumas agências conhecidas
        # (não vamos testar todas, apenas algumas como smoke test)
        assert "agu" in config or "mec" in config or "agricultura" in config

    def test_invalid_path_raises_error(self):
        """Caminho inválido gera FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_site_urls_config(Path("/caminho/inexistente.yaml"))


class TestValidateAgenciesConfig:
    """Testes para validação completa da configuração."""

    def test_validate_with_no_errors(self):
        """Validação sem erros retorna lista vazia."""
        # Assumindo que o arquivo de produção está correto após a correção
        # Este teste pode falhar inicialmente se houver duplicatas
        errors = validate_agencies_config()
        # Não vamos verificar se está vazio aqui, pois esperamos
        # que o teste de integridade abaixo seja mais específico
        assert isinstance(errors, list)

    def test_invalid_path_returns_error(self):
        """Caminho inválido retorna erro descritivo."""
        errors = validate_agencies_config(Path("/caminho/inexistente.yaml"))
        assert len(errors) == 1
        assert "Erro ao carregar configuração" in errors[0]


class TestSiteUrlsConfigIntegrity:
    """
    Testes de integridade do arquivo de produção site_urls.yaml.

    IMPORTANTE: Este teste valida o arquivo real usado em produção.
    Se este teste falhar, significa que há problemas na configuração
    que afetarão o funcionamento dos scrapers.
    """

    def test_production_config_has_no_duplicate_urls(self):
        """
        Arquivo site_urls.yaml de produção não deve ter URLs duplicadas.

        Este teste garante que não há agências diferentes raspando a mesma URL,
        o que causaria desperdício de recursos e potencial duplicação de dados.
        """
        errors = validate_agencies_config()

        # Se houver erros, exibe todas as duplicatas encontradas
        if errors:
            error_msg = (
                "ERRO: Arquivo site_urls.yaml contém URLs duplicadas!\n\n"
                "URLs duplicadas encontradas:\n"
            )
            for error in errors:
                error_msg += f"  - {error}\n"
            error_msg += "\nPor favor, corrija o arquivo removendo as entradas duplicadas."
            pytest.fail(error_msg)

        # Se passou, não há duplicatas
        assert errors == []

    def test_production_config_loads_successfully(self):
        """Arquivo site_urls.yaml de produção pode ser carregado sem erros."""
        config = load_site_urls_config()
        assert isinstance(config, dict)
        assert len(config) > 0

    def test_production_config_has_valid_urls(self):
        """URLs no arquivo de produção são strings não vazias."""
        config = load_site_urls_config()

        # Ignora entradas None (comentadas)
        active_agencies = {k: v for k, v in config.items() if v is not None}

        assert len(active_agencies) > 0, "Nenhuma agência ativa encontrada"

        for agency_key, agency_data in active_agencies.items():
            url = _extract_url(agency_data)
            assert url is not None, f"URL da agência '{agency_key}' não encontrada"
            assert isinstance(url, str), f"URL da agência '{agency_key}' não é string"
            assert url.strip() != "", f"URL da agência '{agency_key}' está vazia"
            assert url.startswith("http"), f"URL da agência '{agency_key}' não começa com http"
