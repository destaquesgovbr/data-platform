"""Testes do GraphQLClient: URL do endpoint e audience do token OIDC.

O `GRAPHQL_API_URL` do Terraform é o `.uri` do Cloud Run, sem path. Um POST na
raiz dá 404 (só `/graphql` responde). O token OIDC precisa do audience que a
graphql-api espera (`GRAPHQL_API_AUDIENCE`), não da URL com path.
"""

from unittest.mock import MagicMock, patch

import pytest

from data_platform.clients.graphql_client import GraphQLClient

RUN_URI = "https://destaquesgovbr-graphql-api-abc123-rj.a.run.app"


@pytest.fixture(autouse=True)
def _sem_audience_na_env(monkeypatch):
    monkeypatch.delenv("GRAPHQL_API_AUDIENCE", raising=False)


class TestUrl:
    @pytest.mark.parametrize("url", [RUN_URI, f"{RUN_URI}/"])
    def test_url_sem_path_ganha_graphql(self, url):
        assert GraphQLClient(url).url == f"{RUN_URI}/graphql"

    @pytest.mark.parametrize(
        "url",
        [f"{RUN_URI}/graphql", "http://localhost:8000/graphql", "https://api.example/v2/graphql"],
    )
    def test_url_com_path_e_mantida(self, url):
        assert GraphQLClient(url).url == url

    def test_execute_faz_post_na_url_normalizada(self):
        client = GraphQLClient(RUN_URI)
        response = MagicMock()
        response.json.return_value = {"data": {"ping": "pong"}}
        with (
            patch.object(client, "_get_auth_headers", return_value={}),
            patch.object(client._http_client, "post", return_value=response) as post,
        ):
            client.execute("query Ping { ping }")
        assert post.call_args[0][0] == f"{RUN_URI}/graphql"


class TestAudience:
    def test_audience_padrao_e_a_origem_da_url(self):
        assert GraphQLClient(f"{RUN_URI}/graphql").audience == RUN_URI

    def test_audience_padrao_para_url_sem_path(self):
        assert GraphQLClient(RUN_URI).audience == RUN_URI

    def test_audience_vem_da_env(self, monkeypatch):
        monkeypatch.setenv("GRAPHQL_API_AUDIENCE", "graphql-api-internal")
        assert GraphQLClient(RUN_URI).audience == "graphql-api-internal"

    def test_audience_explicito_prevalece(self, monkeypatch):
        monkeypatch.setenv("GRAPHQL_API_AUDIENCE", "da-env")
        assert GraphQLClient(RUN_URI, audience="explicito").audience == "explicito"

    def test_token_oidc_pedido_com_o_audience(self, monkeypatch):
        monkeypatch.setenv("GRAPHQL_API_AUDIENCE", "graphql-api-internal")
        client = GraphQLClient(RUN_URI)
        with (
            patch("google.oauth2.id_token.fetch_id_token", return_value="tok") as fetch,
            patch("google.auth.transport.requests.Request"),
        ):
            headers = client._get_auth_headers()
        assert headers == {"Authorization": "Bearer tok"}
        assert fetch.call_args[0][1] == "graphql-api-internal"


class TestCoerceJsonObject:
    """O escalar `JSON` da graphql-api pode chegar como str.

    No `newsById`, o `features` sai cru do asyncpg, que não tem codec de JSONB:
    a coluna chega como texto e o escalar `JSON` repassa a string.
    """

    def test_dict_passa_inalterado(self):
        from data_platform.clients.graphql_client import coerce_json_object

        blob = {"entities": [{"text": "Anvisa"}], "word_count": 3}
        assert coerce_json_object(blob) == blob

    def test_str_json_de_objeto_vira_dict(self):
        from data_platform.clients.graphql_client import coerce_json_object

        assert coerce_json_object('{"annotations_source_hash": "abc", "x": [1]}') == {
            "annotations_source_hash": "abc",
            "x": [1],
        }

    @pytest.mark.parametrize("raw", [None, "", "não é json", "null", "[1, 2]", '"texto"', [], 3])
    def test_ausente_invalido_ou_nao_objeto_vira_vazio(self, raw):
        from data_platform.clients.graphql_client import coerce_json_object

        assert coerce_json_object(raw) == {}
