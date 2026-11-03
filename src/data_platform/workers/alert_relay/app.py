"""Alert Relay — FastAPI application.

Cloud Run service que recebe push do tópico dgb.ops.alerts (incidentes do Cloud
Monitoring via notification channel Pub/Sub, ou mensagens {"text": ...} de
qualquer job) e entrega no canal do Telegram da equipe.

Respostas ao Pub/Sub:
  - 200: entregue, ou não adianta reentregar (envelope inválido, 400 persistente);
  - 503: reentregar (429/5xx/rede, 401/403/404 do Telegram, secret indisponível).

Linha de log estável: alert_relay_sent status=<http> ok=<bool> kind=<incident|text|raw>
state=<open|closed|> test=<bool> policy=<nome> message_id=<pubsub id>.
"""

import base64
import binascii
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from data_platform.workers.alert_relay.formatter import format_alert
from data_platform.workers.alert_relay.secrets import SecretUnavailable, telegram_config
from data_platform.workers.alert_relay.telegram import send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


class RedactBotToken(logging.Filter):
    """Redige bot<id>:<token> de qualquer registro (defesa em profundidade: o principal é
    o httpx/httpcore em WARNING, em telegram.py)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _BOT_TOKEN_RE.sub("bot<redigido>", message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


for _handler in logging.getLogger().handlers:
    if not any(isinstance(f, RedactBotToken) for f in _handler.filters):
        _handler.addFilter(RedactBotToken())

app = FastAPI(title="Alert Relay", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _ack(reason: str) -> JSONResponse:
    logger.error("alert_relay_invalid reason=%s", reason)
    return JSONResponse(status_code=200, content={"status": "ignored", "reason": reason})


@app.post("/process")
async def process(request: Request) -> JSONResponse:
    try:
        envelope = json.loads(await request.body())
    except ValueError:
        return _ack("invalid_json")
    if not isinstance(envelope, dict):
        return _ack("invalid_json")
    message = envelope.get("message") or {}
    data_b64 = message.get("data")
    if not data_b64:
        return _ack("no_data")
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        return _ack("invalid_base64")
    attributes = message.get("attributes") or {}
    message_id = message.get("messageId", "")
    # Secret Manager e Telegram são chamadas bloqueantes: fora do event loop.
    return await run_in_threadpool(_relay, data, attributes, message_id)


def _relay(data: bytes, attributes: dict, message_id: str) -> JSONResponse:
    text, meta = format_alert(data, attributes)

    try:
        token, chat_id, thread_id = telegram_config()
    except SecretUnavailable as e:
        logger.error("alert_relay_secret_unavailable message_id=%s error=%s", message_id, e)
        return JSONResponse(status_code=503, content={"status": "secret_unavailable"})

    result = send_message(token, chat_id, text, thread_id=thread_id)
    log = logger.info if result.ok else logger.error
    log(
        "alert_relay_sent status=%s ok=%s kind=%s state=%s test=%s policy=%s message_id=%s%s",
        result.status,
        str(result.ok).lower(),
        meta["kind"],
        meta["state"],
        str(meta["test"]).lower(),
        json.dumps(meta["policy"], ensure_ascii=False),
        message_id,
        ""
        if result.ok
        else f" retryable={str(result.retryable).lower()} error={result.description!r}",
    )
    if result.ok or not result.retryable:
        return JSONResponse(status_code=200, content={"status": "sent" if result.ok else "dropped"})
    return JSONResponse(
        status_code=503, content={"status": "retry", "telegram_status": result.status}
    )
