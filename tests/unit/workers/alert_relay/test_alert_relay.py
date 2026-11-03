"""Alert Relay: dgb.ops.alerts (Pub/Sub push) → Telegram sendMessage.

Contrato:
  - formata incidentes do Cloud Monitoring (aberto/resolvido) e mensagens genéricas
    {"text", "title", "severity", "source"}; texto cru vira mensagem escapada;
  - marca testes (atributo test=true ou "test": true) com [TESTE];
  - envia com chat_id e, se definido, message_thread_id;
  - 200 quando o Telegram aceita; 503 (Pub/Sub reentrega) em 429/5xx/rede/401/403/404
    e quando o secret não está disponível; 200 (ACK) em 400 persistente e em envelope
    inválido (não adianta reentregar);
  - o token NUNCA aparece em log nem na resposta.
"""

import base64
import json
import logging
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from data_platform.workers.alert_relay import app as app_module
from data_platform.workers.alert_relay import formatter, secrets, telegram

TOKEN = "123456789:AAFakeTokenForTestsOnly_xxxxxxxxxxxx"
CHAT = "-1001234567890"


def _incident(state="open", **over):
    inc = {
        "incident_id": "0.abc",
        "scoping_project_id": "inspire-7-finep",
        "url": "https://console.cloud.google.com/monitoring/alerting/incidents/0.abc",
        "state": state,
        "started_at": 1793680000,
        "ended_at": 1793681800 if state == "closed" else None,
        "summary": "LIVENESS HTTP probe failed > 0 for destaquesgovbr-enrichment-worker",
        "policy_name": "enrichment-worker: instância morta pelo liveness",
        "condition_name": "LIVENESS HTTP probe failed > 0 em 5 min",
        "resource_name": "destaquesgovbr-enrichment-worker-00028-wqr",
        "resource": {
            "type": "cloud_run_revision",
            "labels": {"revision_name": "destaquesgovbr-enrichment-worker-00028-wqr"},
        },
        "documentation": {
            "content": "Verifique artigos sem content_embedding.",
            "mime_type": "text/markdown",
        },
    }
    inc.update(over)
    return {"incident": inc, "version": "1.2"}


def _envelope(payload, attributes=None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return {
        "message": {
            "data": base64.b64encode(raw).decode(),
            "attributes": attributes or {},
            "messageId": "m-1",
        },
        "subscription": "projects/p/subscriptions/dgb.ops.alerts--telegram",
    }


# =============================================================================
# formatter
# =============================================================================


class TestFormatter:
    def test_incidente_aberto(self):
        text, meta = formatter.format_alert(json.dumps(_incident()).encode(), {})
        assert meta == {
            "kind": "incident",
            "state": "open",
            "policy": "enrichment-worker: instância morta pelo liveness",
            "test": False,
        }
        assert "ALERTA" in text
        assert "enrichment-worker: instância morta pelo liveness" in text
        assert "LIVENESS HTTP probe failed &gt; 0" in text  # escapado (HTML)
        assert "destaquesgovbr-enrichment-worker-00028-wqr" in text
        assert (
            '<a href="https://console.cloud.google.com/monitoring/alerting/incidents/0.abc">'
            in text
        )
        assert "Verifique artigos sem content_embedding." in text
        assert "UTC" in text

    def test_incidente_resolvido(self):
        text, meta = formatter.format_alert(json.dumps(_incident("closed")).encode(), {})
        assert meta["state"] == "closed"
        assert "RESOLVIDO" in text
        assert "ALERTA" not in text

    def test_mensagem_generica(self):
        payload = {
            "title": "Scraping",
            "text": "3 agências sem execução <24h>",
            "severity": "warning",
            "source": "monitor_scraping_health",
        }
        text, meta = formatter.format_alert(json.dumps(payload).encode(), {})
        assert meta["kind"] == "text"
        assert "<b>Scraping</b>" in text
        assert "3 agências sem execução &lt;24h&gt;" in text
        assert "monitor_scraping_health" in text

    def test_texto_cru(self):
        text, meta = formatter.format_alert(b"algo <quebrou>", {})
        assert meta["kind"] == "raw"
        assert "algo &lt;quebrou&gt;" in text

    def test_marca_teste_por_atributo(self):
        text, meta = formatter.format_alert(json.dumps(_incident()).encode(), {"test": "true"})
        assert meta["test"] is True
        assert text.startswith("🧪 <b>[TESTE]</b>")

    def test_marca_teste_no_payload_generico(self):
        text, meta = formatter.format_alert(json.dumps({"text": "oi", "test": True}).encode(), {})
        assert meta["test"] is True
        assert "[TESTE]" in text

    def test_limite_do_telegram(self):
        payload = {"text": "x" * 10000}
        text, _ = formatter.format_alert(json.dumps(payload).encode(), {})
        assert len(text) <= formatter.TELEGRAM_MAX_LENGTH


# =============================================================================
# telegram
# =============================================================================


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class TestTelegram:
    def test_envia_chat_e_thread(self, monkeypatch):
        post = MagicMock(return_value=_Resp(200, {"ok": True, "result": {"message_id": 7}}))
        monkeypatch.setattr(telegram.httpx, "post", post)
        res = telegram.send_message(TOKEN, CHAT, "<b>oi</b>", thread_id="42")

        assert res.ok and res.status == 200 and not res.retryable
        body = post.call_args.kwargs["json"]
        assert body["chat_id"] == CHAT
        assert body["message_thread_id"] == 42
        assert body["parse_mode"] == "HTML"
        assert body["text"] == "<b>oi</b>"

    def test_sem_thread_nao_manda_message_thread_id(self, monkeypatch):
        post = MagicMock(return_value=_Resp(200, {"ok": True}))
        monkeypatch.setattr(telegram.httpx, "post", post)
        telegram.send_message(TOKEN, CHAT, "oi", thread_id="")
        assert "message_thread_id" not in post.call_args.kwargs["json"]

    @pytest.mark.parametrize("status", [429, 500, 502, 401, 403, 404])
    def test_status_retentaveis(self, monkeypatch, status):
        monkeypatch.setattr(
            telegram.httpx,
            "post",
            MagicMock(return_value=_Resp(status, {"ok": False, "description": "x"})),
        )
        res = telegram.send_message(TOKEN, CHAT, "oi")
        assert not res.ok and res.retryable and res.status == status

    def test_400_tenta_de_novo_sem_parse_mode(self, monkeypatch):
        post = MagicMock(
            side_effect=[
                _Resp(400, {"ok": False, "description": "Bad Request: can't parse entities"}),
                _Resp(200, {"ok": True}),
            ]
        )
        monkeypatch.setattr(telegram.httpx, "post", post)
        res = telegram.send_message(TOKEN, CHAT, "<b>quebrado")
        assert res.ok
        assert "parse_mode" not in post.call_args_list[1].kwargs["json"]

    def test_400_persistente_nao_e_retentavel(self, monkeypatch):
        monkeypatch.setattr(
            telegram.httpx,
            "post",
            MagicMock(
                return_value=_Resp(400, {"ok": False, "description": "Bad Request: chat not found"})
            ),
        )
        res = telegram.send_message(TOKEN, CHAT, "oi")
        assert not res.ok and not res.retryable and res.status == 400

    def test_erro_de_rede_nao_vaza_token(self, monkeypatch):
        def boom(url, **kw):
            raise httpx.ConnectError(f"falhou ao conectar em {url}")

        monkeypatch.setattr(telegram.httpx, "post", boom)
        res = telegram.send_message(TOKEN, CHAT, "oi")
        assert not res.ok and res.retryable and res.status == 0
        assert TOKEN not in res.description
        assert res.description == "ConnectError"


# =============================================================================
# secrets
# =============================================================================


class TestSecrets:
    @pytest.fixture(autouse=True)
    def _clear(self):
        secrets.clear_cache()
        yield
        secrets.clear_cache()

    def test_le_e_faz_cache(self, monkeypatch):
        fetch = MagicMock(return_value="valor\n")
        monkeypatch.setattr(secrets, "_fetch_latest", fetch)
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        assert secrets.get_secret("s1") == "valor"
        assert secrets.get_secret("s1") == "valor"
        fetch.assert_called_once_with("proj", "s1")

    def test_falha_sem_cache_levanta_secret_unavailable(self, monkeypatch):
        monkeypatch.setattr(secrets, "_fetch_latest", MagicMock(side_effect=RuntimeError("403")))
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        with pytest.raises(secrets.SecretUnavailable):
            secrets.get_secret("s1")

    def test_falha_com_cache_vencido_usa_o_ultimo_valor(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        monkeypatch.setattr(secrets, "_fetch_latest", MagicMock(return_value="v1"))
        assert secrets.get_secret("s1") == "v1"
        secrets._expire_all_for_tests()
        monkeypatch.setattr(secrets, "_fetch_latest", MagicMock(side_effect=RuntimeError("x")))
        assert secrets.get_secret("s1") == "v1"

    def test_valor_vazio_e_indisponivel(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "proj")
        monkeypatch.setattr(secrets, "_fetch_latest", MagicMock(return_value="  \n"))
        with pytest.raises(secrets.SecretUnavailable):
            secrets.get_secret("s1")

    def test_config_do_telegram(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN_SECRET", "tok-secret")
        monkeypatch.setenv("TELEGRAM_CHAT_ID_SECRET", "chat-secret")
        monkeypatch.setenv("TELEGRAM_THREAD_ID", "9")
        values = {"tok-secret": TOKEN, "chat-secret": CHAT}
        monkeypatch.setattr(secrets, "get_secret", lambda sid: values[sid])
        assert secrets.telegram_config() == (TOKEN, CHAT, "9")


# =============================================================================
# app
# =============================================================================


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def config_ok(monkeypatch):
    monkeypatch.setattr(app_module, "telegram_config", lambda: (TOKEN, CHAT, ""))


class TestApp:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200 and resp.json() == {"status": "ok"}

    def test_envia_e_responde_200(self, client, config_ok, monkeypatch, caplog):
        send = MagicMock(return_value=telegram.SendResult(200, True, "", False))
        monkeypatch.setattr(app_module, "send_message", send)
        with caplog.at_level(logging.INFO):
            resp = client.post("/process", json=_envelope(_incident(), {"test": "true"}))

        assert resp.status_code == 200
        args = send.call_args.args
        assert args[0] == TOKEN and args[1] == CHAT
        assert "[TESTE]" in args[2]
        line = next(r.getMessage() for r in caplog.records if "alert_relay_sent" in r.getMessage())
        assert "status=200" in line and "ok=true" in line and "kind=incident" in line
        assert "test=true" in line
        assert TOKEN not in caplog.text

    def test_falha_retentavel_responde_503(self, client, config_ok, monkeypatch, caplog):
        monkeypatch.setattr(
            app_module,
            "send_message",
            MagicMock(return_value=telegram.SendResult(429, False, "Too Many Requests", True)),
        )
        with caplog.at_level(logging.INFO):
            resp = client.post("/process", json=_envelope({"text": "oi"}))
        assert resp.status_code == 503
        assert TOKEN not in resp.text and TOKEN not in caplog.text

    def test_400_persistente_faz_ack(self, client, config_ok, monkeypatch):
        monkeypatch.setattr(
            app_module,
            "send_message",
            MagicMock(return_value=telegram.SendResult(400, False, "Bad Request", False)),
        )
        resp = client.post("/process", json=_envelope({"text": "oi"}))
        assert resp.status_code == 200

    def test_secret_indisponivel_responde_503(self, client, monkeypatch):
        def no_secret():
            raise secrets.SecretUnavailable("ops-alerts-telegram-bot-token")

        monkeypatch.setattr(app_module, "telegram_config", no_secret)
        send = MagicMock()
        monkeypatch.setattr(app_module, "send_message", send)
        resp = client.post("/process", json=_envelope({"text": "oi"}))
        assert resp.status_code == 503
        send.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [{"message": {}}, {"message": {"data": "%%%nao-base64"}}, {"nada": 1}],
    )
    def test_envelope_invalido_faz_ack(self, client, config_ok, monkeypatch, body):
        send = MagicMock()
        monkeypatch.setattr(app_module, "send_message", send)
        resp = client.post("/process", json=body)
        assert resp.status_code == 200
        send.assert_not_called()

    def test_json_invalido_faz_ack(self, client):
        resp = client.post("/process", content=b"{", headers={"content-type": "application/json"})
        assert resp.status_code == 200


# =============================================================================
# O token não pode vazar em log de biblioteca (httpx loga a URL em INFO)
# =============================================================================


def _real_httpx_post(status=200, body=None):
    """httpx.post de verdade (Client + MockTransport): exercita o logger do httpx."""
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body or {"ok": True, "result": {"message_id": 1}})

    def post(url, **kwargs):
        timeout = kwargs.pop("timeout", None)
        with real_client(transport=httpx.MockTransport(handler), timeout=timeout) as c:
            return c.post(url, **kwargs)

    return post


class TestTokenForaDosLogs:
    def test_httpx_real_nao_loga_a_url_com_token(self, monkeypatch, caplog):
        monkeypatch.setattr(telegram.httpx, "post", _real_httpx_post())
        with caplog.at_level(logging.INFO):  # mesmo nível do app em produção
            res = telegram.send_message(TOKEN, CHAT, "oi")
        assert res.ok
        assert TOKEN not in caplog.text
        assert "api.telegram.org/bot" not in caplog.text

    def test_process_ponta_a_ponta_sem_token_no_log(self, client, config_ok, monkeypatch, caplog):
        monkeypatch.setattr(telegram.httpx, "post", _real_httpx_post())
        with caplog.at_level(logging.DEBUG):
            resp = client.post("/process", json=_envelope({"text": "oi"}))
        assert resp.status_code == 200
        assert "alert_relay_sent status=200" in caplog.text
        assert TOKEN not in caplog.text

    def test_filtro_redige_token_de_bot_em_qualquer_log(self):
        from data_platform.workers.alert_relay.app import RedactBotToken

        record = logging.LogRecord(
            "x",
            logging.INFO,
            __file__,
            1,
            "POST https://api.telegram.org/bot%s/sendMessage",
            (TOKEN,),
            None,
        )
        assert RedactBotToken().filter(record) is True
        assert TOKEN not in record.getMessage()
        assert "bot<redigido>/sendMessage" in record.getMessage()

    def test_filtro_esta_nos_handlers_do_root(self):
        from data_platform.workers.alert_relay.app import RedactBotToken

        handlers = logging.getLogger().handlers
        assert any(isinstance(f, RedactBotToken) for h in handlers for f in h.filters)
