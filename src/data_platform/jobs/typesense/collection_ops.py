"""
Operações de coleção Typesense.

Funções utilitárias para gerenciamento de coleções.
"""

import logging
from typing import Any

from data_platform.typesense import (
    get_client,
    delete_collection,
    list_collections,
    COLLECTION_NAME,
)

logger = logging.getLogger(__name__)


def delete_typesense_collection(
    collection_name: str = COLLECTION_NAME,
    confirm: bool = False,
) -> bool:
    """
    Deleta uma coleção do Typesense.

    Args:
        collection_name: Nome da coleção a deletar
        confirm: Se True, pula confirmação interativa

    Returns:
        True se deletado com sucesso
    """
    logger.info(f"Deletando coleção '{collection_name}'...")

    client = get_client()
    return delete_collection(client, collection_name, confirm=confirm)


def list_typesense_collections() -> list[dict[str, Any]]:
    """
    Lista todas as coleções do Typesense.

    Returns:
        Lista de dicionários com informações das coleções
    """
    client = get_client()
    return list_collections(client)


def create_search_key(
    description: str = "Search-only key",
    collections: list[str] | None = None,
    actions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Cria uma chave de API somente leitura para busca.

    Args:
        description: Descrição da chave
        collections: Lista de coleções permitidas (default: [COLLECTION_NAME])
        actions: Lista de ações permitidas (default: ["documents:search"])

    Returns:
        Dicionário com informações da chave criada
    """
    client = get_client()

    collections = collections or [COLLECTION_NAME]
    actions = actions or ["documents:search"]

    key_params = {
        "description": description,
        "actions": actions,
        "collections": collections,
    }

    try:
        result = client.keys.create(key_params)
        logger.info(f"Chave de busca criada: {result['value'][:20]}...")
        return result
    except Exception as e:
        logger.error(f"Erro ao criar chave de busca: {e}")
        raise
