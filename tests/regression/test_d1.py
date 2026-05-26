"""
Testes de regressão da Fase D1 (PLANO-ATUALIZACAO-v2.md §5 Fase D1).

Cobrem cenários explicitamente destacados no plano:

1. Bronze Writer: handler usa GraphQL quando ``GRAPHQL_API_URL`` está setado
   no ambiente; senão faz fallback para PostgreSQL.
2. Feature Worker: payload da mutation ``UPSERT_FEATURES_MUTATION`` enviada
   ao graphql-api usa camelCase (chaves ``uniqueId`` e ``features``), consistente
   com o schema do graphql-api (Strawberry default).
3. Typesense Sync: o mapeamento da resposta GraphQL é robusto contra ``None``
   em campos opcionais (``imageUrl``, ``agencyKey``, etc.) — não quebra,
   e os campos ``None`` simplesmente não aparecem no dict normalizado.
4. DAG compute_clusters: o branch GraphQL é escolhido quando ``GRAPHQL_API_URL``
   está setado.
5. Umami sync DAG: trip-wire — ``sync_umami_to_bigquery.py`` e o job
   ``umami_sync.py`` continuam usando ``psycopg2`` direto e NÃO importam o
   ``graphql_client``. Esse DAG está fora do escopo da migração GraphQL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Teste 1: Bronze Writer alterna entre GraphQL e Postgres conforme env var
# ---------------------------------------------------------------------------


class TestBronzeWriterGraphQLOptIn:
    """Confirma o comportamento opt-in do Bronze Writer mesmo após rebase."""

    def _reset_singletons(self) -> None:
        """Resetar singletons module-level para isolar o teste."""
        from data_platform.workers.bronze_writer import app as bronze_app

        bronze_app._pg = None
        bronze_app._gql_client = None

    def test_bronze_writer_uses_graphql_when_env_set(self):
        """Com GRAPHQL_API_URL no ambiente, _get_gql_client retorna um cliente."""
        self._reset_singletons()

        from data_platform.workers.bronze_writer import app as bronze_app

        with patch.dict(os.environ, {"GRAPHQL_API_URL": "http://graphql.test/graphql"}):
            with patch(
                "data_platform.clients.graphql_client.GraphQLClient"
            ) as MockClient:
                instance = MagicMock()
                MockClient.return_value = instance

                client = bronze_app._get_gql_client()

                assert client is instance, (
                    "Esperado GraphQLClient instanciado quando GRAPHQL_API_URL "
                    "está setado."
                )
                MockClient.assert_called_once_with(url="http://graphql.test/graphql")

        # E o fallback: sem env var, _get_gql_client devolve None.
        self._reset_singletons()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GRAPHQL_API_URL", None)
            client_none = bronze_app._get_gql_client()
            assert client_none is None, (
                "Sem GRAPHQL_API_URL deve devolver None → handler cai no PG."
            )


# ---------------------------------------------------------------------------
# Teste 2: Feature Worker envia camelCase consistente com Strawberry
# ---------------------------------------------------------------------------


class TestFeatureWorkerMutationPayloadCamelCase:
    """O payload da mutation upsertFeatures deve usar chaves camelCase."""

    def test_feature_worker_mutation_payload_uses_camelcase_keys(self):
        from data_platform.workers.feature_worker.handler import (
            _upsert_features_via_graphql,
        )

        gql_client = MagicMock()
        features = {
            "word_count": 250,
            "quality_score": 0.87,
            "has_image": True,
        }

        _upsert_features_via_graphql("agency-2026-01-01-x", features, gql_client)

        gql_client.mutate.assert_called_once()
        call_args = gql_client.mutate.call_args
        variables = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("variables")
        )

        # Chaves do envelope da mutation são camelCase (Strawberry default).
        assert set(variables.keys()) == {"uniqueId", "features"}, (
            f"Variáveis esperadas camelCase, recebido: {variables.keys()}"
        )
        # `uniqueId` (camelCase), NÃO `unique_id`.
        assert "unique_id" not in variables
        assert variables["uniqueId"] == "agency-2026-01-01-x"

        # `features` é serializado como JSON string (assinatura da mutation
        # exige scalar JSON). O valor interno pode permanecer snake_case porque
        # já é um payload aplicação-específica armazenado como JSONB no PG.
        parsed = json.loads(variables["features"])
        assert parsed["word_count"] == 250
        assert parsed["quality_score"] == 0.87


# ---------------------------------------------------------------------------
# Teste 3: Typesense sync — parse robusto contra None em campos opcionais
# ---------------------------------------------------------------------------


class TestTypesenseSyncHandlesNoneInOptionalFields:
    """Resposta GraphQL com null em campos opcionais não pode quebrar mapeamento."""

    def test_typesense_sync_handles_none_in_optional_fields(self):
        from data_platform.workers.typesense_sync.handler import _map_graphql_row

        # Resposta mínima viável onde quase todos os campos opcionais são None.
        gql_row = {
            "uniqueId": "art-with-nones",
            "title": "Mínimo",
            "url": "https://example.gov.br/x",
            "imageUrl": None,
            "videoUrl": None,
            "content": "abc",
            "summary": None,
            "subtitle": None,
            "editorialLead": None,
            "category": None,
            "tags": None,
            "agencyKey": None,
            "agencyName": None,
            "publishedAt": None,
            "extractedAt": None,
            "themL1Code": None,
            "themL1Label": None,
            "themL2Code": None,
            "themL2Label": None,
            "themL3Code": None,
            "themL3Label": None,
            "mostSpecificThemeCode": None,
            "mostSpecificThemeLabel": None,
            "contentEmbedding": None,
            "sentimentLabel": None,
            "sentimentScore": None,
            "trendingScore": None,
            "wordCount": None,
            "hasImage": None,
            "hasVideo": None,
            "imageBroken": None,
            "readabilityFlesch": None,
        }

        # Não deve levantar exceção.
        mapped = _map_graphql_row(gql_row)

        # Chaves obrigatórias presentes.
        assert mapped["unique_id"] == "art-with-nones"
        assert mapped["title"] == "Mínimo"
        assert mapped["content"] == "abc"

        # Campos None foram omitidos do dict resultante (estratégia atual).
        assert "image" not in mapped, "imageUrl=None não deve produzir entrada 'image'"
        assert "agency" not in mapped, "agencyKey=None não deve produzir 'agency'"
        assert "content_embedding" not in mapped

        # publishedAt=None: o helper não deve injetar published_at_ts.
        assert "published_at_ts" not in mapped


# ---------------------------------------------------------------------------
# Teste 4: DAG compute_clusters escolhe GraphQL quando URL setado
# ---------------------------------------------------------------------------


class TestComputeClustersDagGraphQLBranch:
    """Verifica que o DAG escolhe o caminho GraphQL quando env var está setada."""

    def test_dag_compute_clusters_uses_graphql_path_when_url_set(self):
        # Lê o arquivo do DAG e confirma que a função de orquestração
        # roteia pelo env var corretamente. Não importamos o módulo direto
        # porque ele declara um @dag em import time (precisa de Airflow).
        dag_path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "data_platform"
            / "dags"
            / "compute_clusters.py"
        )
        source = dag_path.read_text(encoding="utf-8")

        # O branch GraphQL deve existir e ser escolhido condicionalmente.
        assert "GRAPHQL_API_URL" in source, (
            "compute_clusters deve checar GRAPHQL_API_URL para escolher GraphQL"
        )
        assert "_run_via_graphql" in source
        assert "_run_via_postgres" in source

        # A escolha do branch deve ser explícita: `if graphql_url:` ou
        # condição equivalente que delega para o branch GraphQL quando
        # a env var está presente.
        assert "if graphql_url" in source or "if graphql_url:" in source, (
            "compute_clusters deve ramificar com base no valor de "
            "GRAPHQL_API_URL"
        )
        # E o branch GraphQL deve importar o GraphQLClient.
        assert "from data_platform.clients.graphql_client import GraphQLClient" in source


# ---------------------------------------------------------------------------
# Teste 5: Umami DAG e job NÃO usam graphql_client (trip-wire)
# ---------------------------------------------------------------------------


class TestUmamiSyncDagUnchanged:
    """sync_umami_to_bigquery permanece fora da migração GraphQL."""

    def test_umami_sync_dag_unchanged(self):
        repo_root = Path(__file__).resolve().parents[2]
        dag_path = repo_root / "src" / "data_platform" / "dags" / "sync_umami_to_bigquery.py"
        job_path = repo_root / "src" / "data_platform" / "jobs" / "bigquery" / "umami_sync.py"

        assert dag_path.exists(), "sync_umami_to_bigquery.py deve existir"
        assert job_path.exists(), "umami_sync.py job deve existir"

        dag_source = dag_path.read_text(encoding="utf-8")
        job_source = job_path.read_text(encoding="utf-8")

        # O job deve importar psycopg2 (PG direto).
        assert "import psycopg2" in job_source, (
            "umami_sync.py deve continuar importando psycopg2 (PG direto, "
            "não está no escopo da migração GraphQL)."
        )

        # Nem o DAG nem o job podem importar o graphql_client.
        for name, source in (("DAG", dag_source), ("job", job_source)):
            assert "graphql_client" not in source, (
                f"{name} sync_umami não deve importar graphql_client — "
                "este DAG continua direct-PG por design."
            )
            assert "GraphQLClient" not in source, (
                f"{name} sync_umami não deve referenciar GraphQLClient."
            )
            assert "GRAPHQL_API_URL" not in source, (
                f"{name} sync_umami não deve ler GRAPHQL_API_URL."
            )
