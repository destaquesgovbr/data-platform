"""
Cliente Typesense - Conexão e configuração.
"""

import logging
import os
import time

import requests
import typesense

logger = logging.getLogger(__name__)


def get_client(
    host: str | None = None,
    port: str | None = None,
    api_key: str | None = None,
    protocol: str = "http",
    timeout: int = 10,
) -> typesense.Client:
    """
    Cria e retorna um cliente Typesense configurado.

    Args:
        host: Host do servidor Typesense (default: TYPESENSE_HOST env var ou 'localhost')
        port: Porta do servidor (default: TYPESENSE_PORT env var ou '8108')
        api_key: Chave de API (default: TYPESENSE_API_KEY env var)
        protocol: Protocolo de conexão (default: 'http')
        timeout: Timeout de conexão em segundos (default: 10)

    Returns:
        typesense.Client: Cliente Typesense configurado

    Raises:
        ValueError: Se api_key não for fornecida
    """
    host = host or os.getenv("TYPESENSE_HOST", "localhost")
    port = port or os.getenv("TYPESENSE_PORT", "8108")
    api_key = api_key or os.getenv(
        "TYPESENSE_API_KEY", "govbrnews_api_key_change_in_production"
    )

    if not api_key:
        raise ValueError("TYPESENSE_API_KEY deve ser configurada")

    client = typesense.Client(
        {
            "nodes": [{"host": host, "port": port, "protocol": protocol}],
            "api_key": api_key,
            "connection_timeout_seconds": timeout,
        }
    )

    return client


def wait_for_typesense(
    host: str | None = None,
    port: str | None = None,
    api_key: str | None = None,
    max_retries: int = 30,
    retry_interval: int = 2,
) -> typesense.Client | None:
    """
    Aguarda o servidor Typesense ficar pronto e retorna um cliente.

    Args:
        host: Host do servidor Typesense
        port: Porta do servidor
        api_key: Chave de API
        max_retries: Número máximo de tentativas (default: 30)
        retry_interval: Intervalo entre tentativas em segundos (default: 2)

    Returns:
        typesense.Client se conectado, None se timeout
    """
    host = host or os.getenv("TYPESENSE_HOST", "localhost")
    port = port or os.getenv("TYPESENSE_PORT", "8108")

    retry_count = 0

    while retry_count < max_retries:
        try:
            health_url = f"http://{host}:{port}/health"
            response = requests.get(health_url, timeout=5)

            if response.status_code == 200:
                logger.info("Typesense está pronto!")
                return get_client(host=host, port=port, api_key=api_key)

        except Exception as e:
            retry_count += 1
            logger.info(
                f"Typesense não está pronto, tentativa {retry_count}/{max_retries}: {e}"
            )
            time.sleep(retry_interval)

    logger.error("Typesense não ficou pronto após todas as tentativas")
    return None
