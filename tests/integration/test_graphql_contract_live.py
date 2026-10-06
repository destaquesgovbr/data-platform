"""Contrato GraphQL ao vivo: snapshot do SDL e operações contra a graphql-api pública.

Fica fora de ``tests/unit`` para o CI (que roda só ``tests/unit``) não depender da
produção. Só envia a query de introspecção (leitura, sem autenticação).

    pytest tests/integration/test_graphql_contract_live.py -m requires_network

``GRAPHQL_API_INTROSPECTION_URL`` troca o endpoint (por exemplo, uma graphql-api local).
"""

import os

import pytest
from graphql import build_schema, parse, validate

from tests.fixtures.refresh_graphql_schema import DEFAULT_URL, SNAPSHOT_PATH, fetch_sdl
from tests.unit.clients.test_graphql_contract import OPERATIONS

pytestmark = pytest.mark.requires_network

URL = os.environ.get("GRAPHQL_API_INTROSPECTION_URL") or DEFAULT_URL


@pytest.fixture(scope="module")
def live_sdl() -> str:
    try:
        return fetch_sdl(URL)
    except Exception as exc:  # rede indisponível não é falha de contrato
        pytest.skip(f"graphql-api inacessível ({URL}): {exc}")


def test_snapshot_igual_a_introspeccao_ao_vivo(live_sdl: str):
    assert live_sdl == SNAPSHOT_PATH.read_text(encoding="utf-8"), (
        "SDL ao vivo divergiu do snapshot: rode python tests/fixtures/refresh_graphql_schema.py"
    )


@pytest.mark.parametrize("document", [pytest.param(doc, id=name) for name, doc, _ in OPERATIONS])
def test_operacao_valida_contra_o_sdl_ao_vivo(document: str, live_sdl: str):
    errors = validate(build_schema(live_sdl), parse(document))
    assert not errors, "\n".join(e.message for e in errors)
