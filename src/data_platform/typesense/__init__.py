"""
Módulo Typesense - Indexação e busca de notícias.

Este módulo fornece funcionalidades para:
- Conexão com o servidor Typesense
- Gerenciamento de coleções (criar, deletar, listar)
- Indexação de documentos com suporte a embeddings
- Utilitários para processamento de dados
"""

from data_platform.typesense.client import get_client, wait_for_typesense
from data_platform.typesense.collection import (
    COLLECTION_NAME,
    COLLECTION_SCHEMA,
    create_collection,
    delete_collection,
    list_collections,
)
from data_platform.typesense.indexer import (
    index_documents,
    prepare_document,
    run_test_queries,
)
from data_platform.typesense.utils import calculate_published_week

__all__ = [
    # Client
    "get_client",
    "wait_for_typesense",
    # Collection
    "COLLECTION_NAME",
    "COLLECTION_SCHEMA",
    "create_collection",
    "delete_collection",
    "list_collections",
    # Indexer
    "index_documents",
    "prepare_document",
    "run_test_queries",
    # Utils
    "calculate_published_week",
]
