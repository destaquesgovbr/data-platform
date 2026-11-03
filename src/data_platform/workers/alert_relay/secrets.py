"""Leitura dos secrets do Telegram no Secret Manager, em runtime e com cache.

O Terraform cria só o recurso dos secrets; o valor é adicionado fora dele. Ler em
runtime (e não como env do Cloud Run) deixa o serviço subir antes de o valor
existir e dispensa redeploy na rotação. Falha de leitura com valor em cache usa o
último valor conhecido.
"""

import base64
import os
import threading
import time

_TTL_SECONDS = 300
_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


class SecretUnavailable(RuntimeError):
    """Secret sem versão, sem permissão ou API indisponível (o relay responde 503)."""


def _fetch_latest(project: str, secret_id: str) -> str:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    url = (
        f"https://secretmanager.googleapis.com/v1/projects/{project}"
        f"/secrets/{secret_id}/versions/latest:access"
    )
    resp = session.get(url, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Secret Manager HTTP {resp.status_code}")
    return base64.b64decode(resp.json()["payload"]["data"]).decode("utf-8")


def get_secret(secret_id: str) -> str:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(secret_id)
    if cached and cached[1] > now:
        return cached[0]
    try:
        value = _fetch_latest(os.environ.get("GCP_PROJECT_ID", ""), secret_id).strip()
        if not value:
            raise RuntimeError("valor vazio")
    except Exception as e:
        if cached:
            return cached[0]
        raise SecretUnavailable(f"{secret_id}: {type(e).__name__}: {e}") from None
    with _lock:
        _cache[secret_id] = (value, now + _TTL_SECONDS)
    return value


def telegram_config() -> tuple[str, str, str]:
    """(token, chat_id, thread_id). Nomes dos secrets nas envs *_SECRET (Terraform)."""
    token = get_secret(os.environ.get("TELEGRAM_BOT_TOKEN_SECRET", "ops-alerts-telegram-bot-token"))
    chat_id = get_secret(os.environ.get("TELEGRAM_CHAT_ID_SECRET", "ops-alerts-telegram-chat-id"))
    return token, chat_id, os.environ.get("TELEGRAM_THREAD_ID", "").strip()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _expire_all_for_tests() -> None:
    with _lock:
        for key, (value, _) in list(_cache.items()):
            _cache[key] = (value, 0.0)
