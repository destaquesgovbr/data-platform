"""
Cliente Typesense - Conexão e configuração.
"""

import json
import logging
import os
import time

import requests
import typesense

logger = logging.getLogger(__name__)


def _parse_write_conn() -> tuple[str | None, str | None, str | None, str]:
    """Parse TYPESENSE_WRITE_CONN JSON env var (host, port, apiKey, protocol)."""
    raw = os.getenv("TYPESENSE_WRITE_CONN", "")
    if not raw:
        return None, None, None, "http"
    try:
        conn = json.loads(raw)
        return (
            conn.get("host"),
            str(conn.get("port", "")),
            conn.get("apiKey"),
            conn.get("protocol", "http"),
        )
    except (json.JSONDecodeError, TypeError):
        return None, None, None, "http"


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
        api_key: Chave de API (default: Airflow Variable ou TYPESENSE_API_KEY env var)
        protocol: Protocolo de conexão (default: 'http')
        timeout: Timeout de conexão em segundos (default: 10)

    Returns:
        typesense.Client: Cliente Typesense configurado

    Raises:
        ValueError: Se api_key não for fornecida
    """
    # Try TYPESENSE_WRITE_CONN JSON first, then individual env vars
    conn_host, conn_port, conn_key, conn_protocol = _parse_write_conn()

    # Try Airflow Variable for API key (after WRITE_CONN, before env vars)
    if not conn_key:
        try:
            from airflow.models import Variable
            conn_key = Variable.get("typesense_api_key", default_var=None)
        except Exception:
            # Airflow Variable not available (running outside Airflow or variable not set)
            pass

    host = host or conn_host or os.getenv("TYPESENSE_HOST", "localhost")
    port = port or conn_port or os.getenv("TYPESENSE_PORT", "8108")
    api_key = api_key or conn_key or os.getenv(
        "TYPESENSE_API_KEY", "govbrnews_api_key_change_in_production"
    )
    if conn_protocol != "http":
        protocol = conn_protocol

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
