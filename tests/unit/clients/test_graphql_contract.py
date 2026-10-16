"""Contrato GraphQL: toda constante ``*_QUERY``/``*_MUTATION`` de
``data_platform.clients.graphql_client`` é uma operação nomeada, do tipo certo e
válida contra o SDL da graphql-api.

O SDL vem de ``tests/fixtures/graphql_api_schema.graphql``, snapshot obtido por
introspecção de leitura (``python tests/fixtures/refresh_graphql_schema.py``).
``GRAPHQL_SCHEMA_SDL=<arquivo>`` troca o SDL, por exemplo para pré-validar contra
o schema de um PR da graphql-api. A comparação com a API ao vivo fica fora de
``tests/unit`` (``tests/integration/test_graphql_contract_live.py``).

Além da validação, os mapeamentos camelCase → snake_case dos handlers só podem
ler campos que a query correspondente seleciona: foi assim que ``themL*``
(inexistente no schema) ficou anos sem ser notado.
"""

import os
from pathlib import Path

import pytest
from graphql import (
    FieldNode,
    GraphQLSchema,
    OperationDefinitionNode,
    OperationType,
    build_schema,
    parse,
    validate,
)

from data_platform.clients import graphql_client

SNAPSHOT_PATH = Path(__file__).parents[2] / "fixtures" / "graphql_api_schema.graphql"

_SUFFIX_TO_OPERATION = {
    "_QUERY": OperationType.QUERY,
    "_MUTATION": OperationType.MUTATION,
}


def _collect_operations() -> list[tuple[str, str, OperationType]]:
    """(nome, documento, tipo esperado) de toda constante str ``*_QUERY``/``*_MUTATION``."""
    found = []
    for attr, value in sorted(vars(graphql_client).items()):
        if not isinstance(value, str):
            continue
        for suffix, op_type in _SUFFIX_TO_OPERATION.items():
            if attr.endswith(suffix):
                found.append((attr, value, op_type))
    return found


OPERATIONS = _collect_operations()


def _operations(document: str) -> list[OperationDefinitionNode]:
    return [d for d in parse(document).definitions if isinstance(d, OperationDefinitionNode)]


def selected_fields(document: str) -> set[str]:
    """Campos selecionados sob o campo raiz da (única) operação do documento."""
    (operation,) = _operations(document)
    (root,) = operation.selection_set.selections
    assert isinstance(root, FieldNode)
    assert root.selection_set is not None, f"{root.name.value} não tem sub-seleção"
    return {s.name.value for s in root.selection_set.selections if isinstance(s, FieldNode)}


@pytest.fixture(scope="module")
def schema() -> GraphQLSchema:
    path = Path(os.environ.get("GRAPHQL_SCHEMA_SDL") or SNAPSHOT_PATH)
    return build_schema(path.read_text(encoding="utf-8"))


def test_coleta_encontra_todas_as_operacoes_conhecidas():
    names = {name for name, _, _ in OPERATIONS}
    assert {
        "NEWS_BY_ID_QUERY",
        "NEWS_FOR_TYPESENSE_QUERY",
        "NEWS_BATCH_FOR_BIGQUERY_QUERY",
        "SIMILAR_ARTICLES_QUERY",
        "INTEGRITY_BATCH_QUERY",
        "UPSERT_FEATURES_MUTATION",
        "BATCH_UPSERT_FEATURES_MUTATION",
        "UPDATE_TYPESENSE_FIELD_MUTATION",
    } <= names


@pytest.mark.parametrize(
    ("document", "expected"),
    [pytest.param(doc, op, id=name) for name, doc, op in OPERATIONS],
)
def test_constante_e_uma_operacao_nomeada_do_tipo_do_sufixo(document: str, expected: OperationType):
    operations = _operations(document)
    assert len(operations) == 1, "uma operação por constante"
    (operation,) = operations
    assert operation.operation is expected
    assert operation.name is not None, "operação anônima: nomeie a operação"


@pytest.mark.parametrize("document", [pytest.param(doc, id=name) for name, doc, _ in OPERATIONS])
def test_operacao_valida_contra_o_sdl(document: str, schema: GraphQLSchema):
    errors = validate(schema, parse(document))
    assert not errors, "\n".join(e.message for e in errors)


def test_schema_usa_string_para_identificadores(schema: GraphQLSchema):
    """O schema não tem o escalar `ID`; a API responde `Unknown type 'ID'`."""
    assert "ID" not in schema.type_map
    assert str(schema.query_type.fields["newsById"].args["uniqueId"].type) == "String!"


# ---------------------------------------------------------------------------
# Mapeamentos dos handlers ⊆ campos selecionados
# ---------------------------------------------------------------------------


def test_typesense_sync_so_le_campos_selecionados():
    from data_platform.workers.typesense_sync.handler import _GRAPHQL_TO_SNAKE

    selected = selected_fields(graphql_client.NEWS_FOR_TYPESENSE_QUERY)
    assert set(_GRAPHQL_TO_SNAKE) <= selected, set(_GRAPHQL_TO_SNAKE) - selected
    assert "features" in selected  # entities/view_count saem do blob


def test_bronze_writer_so_le_campos_selecionados():
    from data_platform.workers.bronze_writer.handler import _GRAPHQL_TO_SNAKE

    selected = selected_fields(graphql_client.NEWS_BY_ID_QUERY)
    assert set(_GRAPHQL_TO_SNAKE) <= selected, set(_GRAPHQL_TO_SNAKE) - selected


def test_feature_worker_campos_necessarios_selecionados():
    selected = selected_fields(graphql_client.NEWS_BY_ID_QUERY)
    assert {"uniqueId", "content", "imageUrl", "videoUrl", "publishedAt", "features"} <= selected


def test_bigquery_so_le_campos_selecionados():
    from data_platform.jobs.bigquery.sync_to_bigquery import _BIGQUERY_GRAPHQL_FIELDS

    selected = selected_fields(graphql_client.NEWS_BATCH_FOR_BIGQUERY_QUERY)
    fields = set(_BIGQUERY_GRAPHQL_FIELDS.values())
    assert fields <= selected, fields - selected
    assert "features" in selected  # char_count, paragraph_count, publication_* saem do blob
