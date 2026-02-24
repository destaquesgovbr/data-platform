"""
Módulo de validação para configurações de scrapers.

Este módulo fornece funções para validar o arquivo site_urls.yaml,
detectando URLs duplicadas e outros problemas de configuração.
"""

from pathlib import Path
from typing import Any

import yaml


def normalize_url(url: str) -> str:
    """
    Normaliza uma URL para comparação.

    Remove trailing slashes e converte para lowercase para
    garantir que URLs equivalentes sejam detectadas como duplicatas.

    Args:
        url: URL a ser normalizada

    Returns:
        URL normalizada
    """
    return url.rstrip("/").lower()


def find_duplicate_urls(agencies_config: dict[str, str]) -> list[tuple[str, list[str]]]:
    """
    Encontra todas as URLs duplicadas e suas agências associadas.

    Args:
        agencies_config: Dicionário {agency_key: url}

    Returns:
        Lista de tuplas (url_normalizada, [agency_keys_que_usam_essa_url])
        Apenas URLs que aparecem mais de uma vez são retornadas
    """
    # Mapa de URL normalizada -> lista de agências que usam essa URL
    url_to_agencies: dict[str, list[str]] = {}

    for agency_key, url in agencies_config.items():
        # Ignora entradas comentadas (valor None) ou vazias
        if url is None or not url:
            continue

        normalized = normalize_url(url)
        if normalized not in url_to_agencies:
            url_to_agencies[normalized] = []
        url_to_agencies[normalized].append(agency_key)

    # Retorna apenas URLs duplicadas (2+ agências)
    duplicates = [(url, agencies) for url, agencies in url_to_agencies.items() if len(agencies) > 1]

    return duplicates


def validate_no_duplicate_urls(agencies_config: dict[str, str]) -> list[str]:
    """
    Valida que não há URLs duplicadas entre agências.

    Args:
        agencies_config: Dicionário {agency_key: url}

    Returns:
        Lista de mensagens de erro descritivas (vazia se válido)
    """
    duplicates = find_duplicate_urls(agencies_config)

    if not duplicates:
        return []

    errors = []
    for url, agencies in duplicates:
        agencies_str = ", ".join(sorted(agencies))
        errors.append(
            f"URL duplicada encontrada: '{url}' "
            f"está sendo usada por {len(agencies)} agências: {agencies_str}"
        )

    return errors


def load_site_urls_config(config_path: Path | None = None) -> dict[str, str]:
    """
    Carrega configuração de site_urls.yaml.

    Args:
        config_path: Caminho para o arquivo YAML. Se None, usa o caminho padrão
                     relativo a este módulo

    Returns:
        Dicionário {agency_key: url} da seção 'agencies'

    Raises:
        FileNotFoundError: Se o arquivo não existir
        yaml.YAMLError: Se o arquivo YAML for inválido
        KeyError: Se a seção 'agencies' não existir no YAML
    """
    if config_path is None:
        # Usa caminho relativo a este módulo
        module_dir = Path(__file__).parent
        config_path = module_dir / "site_urls.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict) or "agencies" not in config:
        raise KeyError(
            f"Arquivo YAML inválido: esperado chave 'agencies' no nível raiz. "
            f"Encontrado: {list(config.keys()) if isinstance(config, dict) else type(config)}"
        )

    agencies = config["agencies"]
    if not isinstance(agencies, dict):
        raise TypeError(
            f"Seção 'agencies' deve ser um dicionário. Encontrado: {type(agencies)}"
        )

    return agencies


def validate_agencies_config(config_path: Path | None = None) -> list[str]:
    """
    Executa todas as validações na configuração de agências.

    Args:
        config_path: Caminho para o arquivo YAML. Se None, usa o caminho padrão

    Returns:
        Lista de mensagens de erro (vazia se todas as validações passarem)

    Example:
        >>> errors = validate_agencies_config()
        >>> if errors:
        ...     for error in errors:
        ...         print(f"Erro: {error}")
        ...     sys.exit(1)
        ... else:
        ...     print("Validação OK!")
    """
    try:
        agencies_config = load_site_urls_config(config_path)
    except (FileNotFoundError, yaml.YAMLError, KeyError, TypeError) as e:
        return [f"Erro ao carregar configuração: {e}"]

    # Por enquanto, apenas validação de URLs duplicadas
    # Futuras validações podem ser adicionadas aqui
    errors = validate_no_duplicate_urls(agencies_config)

    return errors
