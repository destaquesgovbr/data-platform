"""Envio para o Telegram (Bot API sendMessage).

O token compõe a URL da Bot API: ela nunca é logada nem devolvida. Erros de rede
viram só o nome da exceção (a mensagem do httpx pode conter a URL).
"""

from dataclasses import dataclass

import httpx

_API = "https://api.telegram.org"
_RETRYABLE = {401, 403, 404, 408, 409, 429}


@dataclass(frozen=True)
class SendResult:
    status: int  # HTTP do Telegram; 0 = falha de rede
    ok: bool
    description: str
    retryable: bool


def _post(token: str, body: dict, timeout: float) -> tuple[int, dict]:
    resp = httpx.post(f"{_API}/bot{token}/sendMessage", json=body, timeout=timeout)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data if isinstance(data, dict) else {}


def send_message(
    token: str, chat_id: str, text: str, thread_id: str | None = None, timeout: float = 10.0
) -> SendResult:
    body: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id:
        body["message_thread_id"] = int(thread_id)

    try:
        status, data = _post(token, body, timeout)
        if status == 400:
            # HTML que o Telegram não aceitou: tenta de novo como texto puro.
            body.pop("parse_mode", None)
            status, data = _post(token, body, timeout)
    except httpx.HTTPError as e:
        return SendResult(0, False, type(e).__name__, True)

    ok = status == 200 and bool(data.get("ok"))
    description = str(data.get("description", ""))[:300]
    retryable = not ok and (status >= 500 or status in _RETRYABLE)
    return SendResult(status, ok, description, retryable)
