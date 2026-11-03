"""Formata a mensagem do tópico dgb.ops.alerts para o Telegram (parse_mode HTML).

Entradas aceitas (o relay é genérico):
  - incidente do Cloud Monitoring (notification channel type=pubsub, JSON {"incident": {...},
    "version": "1.2"});
  - mensagem genérica JSON {"text": ..., "title"?: ..., "severity"?: info|warning|critical,
    "source"?: ..., "test"?: bool} publicada por qualquer job;
  - qualquer outro conteúdo vira texto cru (escapado).

Testes (atributo `test=true` ou `"test": true`) saem com o prefixo 🧪 [TESTE].
"""

import html
import json
from datetime import UTC, datetime
from typing import Any

TELEGRAM_MAX_LENGTH = 4096

_SEVERITY_ICON = {"critical": "🔴", "error": "🔴", "warning": "⚠️", "info": "ℹ️"}
_FIELD_LIMITS = {"summary": 1200, "doc": 800, "text": 3500, "title": 200}


def _esc(value: Any, limit: int | None = None) -> str:
    text = "" if value is None else str(value)
    if limit is not None and len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=False)


def _ts(epoch: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch), tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _is_test(attributes: dict[str, str], payload: dict[str, Any] | None) -> bool:
    if str(attributes.get("test", "")).lower() in ("1", "true", "yes"):
        return True
    return bool(payload and payload.get("test") is True)


def _format_incident(incident: dict[str, Any]) -> list[str]:
    state = str(incident.get("state", "")).lower()
    policy = incident.get("policy_name") or "Alerta sem nome"
    if state == "closed":
        lines = [f"✅ <b>RESOLVIDO</b> · {_esc(policy, _FIELD_LIMITS['title'])}"]
    else:
        lines = [f"🔴 <b>ALERTA</b> · {_esc(policy, _FIELD_LIMITS['title'])}"]
    if incident.get("summary"):
        lines.append(_esc(incident["summary"], _FIELD_LIMITS["summary"]))
    if incident.get("condition_name"):
        lines.append(f"Condição: {_esc(incident['condition_name'], 300)}")
    resource = incident.get("resource_name") or (incident.get("resource") or {}).get("type")
    if resource:
        lines.append(f"Recurso: <code>{_esc(resource, 300)}</code>")
    started = _ts(incident.get("started_at"))
    if started:
        lines.append(f"Início: {started}")
    ended = _ts(incident.get("ended_at"))
    if state == "closed" and ended:
        lines.append(f"Fim: {ended}")
    doc = (incident.get("documentation") or {}).get("content")
    if doc and state != "closed":
        lines.append(f"<i>{_esc(doc.strip(), _FIELD_LIMITS['doc'])}</i>")
    url = incident.get("url")
    if isinstance(url, str) and url.startswith("https://"):
        lines.append(f'<a href="{html.escape(url, quote=True)}">Abrir no Cloud Monitoring</a>')
    return lines


def _format_generic(payload: dict[str, Any]) -> list[str]:
    icon = _SEVERITY_ICON.get(str(payload.get("severity", "")).lower(), "ℹ️")
    lines = []
    if payload.get("title"):
        lines.append(f"{icon} <b>{_esc(payload['title'], _FIELD_LIMITS['title'])}</b>")
    text = _esc(payload.get("text"), _FIELD_LIMITS["text"])
    lines.append(text if lines else f"{icon} {text}")
    if payload.get("source"):
        lines.append(f"<i>{_esc(payload['source'], 200)}</i>")
    return lines


def format_alert(data: bytes, attributes: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """Devolve (texto HTML para o Telegram, metadados para log)."""
    payload: dict[str, Any] | None = None
    try:
        decoded = json.loads(data)
        if isinstance(decoded, dict):
            payload = decoded
    except (ValueError, UnicodeDecodeError):
        payload = None

    meta: dict[str, Any]
    if payload is not None and isinstance(payload.get("incident"), dict):
        incident = payload["incident"]
        lines = _format_incident(incident)
        meta = {
            "kind": "incident",
            "state": str(incident.get("state", "")).lower() or "unknown",
            "policy": incident.get("policy_name") or "",
        }
    elif payload is not None and "text" in payload:
        lines = _format_generic(payload)
        meta = {"kind": "text", "state": "", "policy": payload.get("title") or ""}
    else:
        raw = data.decode("utf-8", errors="replace")
        lines = [f"ℹ️ {_esc(raw, _FIELD_LIMITS['text'])}"]
        meta = {"kind": "raw", "state": "", "policy": ""}

    meta["test"] = _is_test(attributes, payload)
    if meta["test"]:
        lines[0] = f"🧪 <b>[TESTE]</b> {lines[0]}"

    text = "\n".join(lines)
    if len(text) > TELEGRAM_MAX_LENGTH:  # salvaguarda (os campos já têm limite)
        text = html.escape(html.unescape(text)[: TELEGRAM_MAX_LENGTH - 200], quote=False) + "…"
    return text, meta
