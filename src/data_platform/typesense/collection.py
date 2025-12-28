"""
Gerenciamento de coleções Typesense.
"""

import logging
import time
from typing import Any

import typesense
from typesense.exceptions import ObjectNotFound

logger = logging.getLogger(__name__)

COLLECTION_NAME = "news"

COLLECTION_SCHEMA: dict[str, Any] = {
    "name": COLLECTION_NAME,
    "fields": [
        {"name": "unique_id", "type": "string", "facet": True, "sort": True},
        {"name": "agency", "type": "string", "facet": True, "optional": True},
        {
            "name": "published_at",
            "type": "int64",
            "facet": False,
        },  # Unix timestamp - required for sorting
        {"name": "title", "type": "string", "facet": False, "optional": True},
        {"name": "url", "type": "string", "facet": False, "optional": True},
        {"name": "image", "type": "string", "facet": False, "optional": True},
        {"name": "category", "type": "string", "facet": True, "optional": True},
        {"name": "content", "type": "string", "facet": False, "optional": True},
        {"name": "summary", "type": "string", "facet": False, "optional": True},
        {"name": "subtitle", "type": "string", "facet": False, "optional": True},
        {"name": "editorial_lead", "type": "string", "facet": False, "optional": True},
        {"name": "extracted_at", "type": "int64", "facet": False, "optional": True},
        {
            "name": "theme_1_level_1_code",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "theme_1_level_1_label",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "theme_1_level_2_code",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "theme_1_level_2_label",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "theme_1_level_3_code",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "theme_1_level_3_label",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "most_specific_theme_code",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {
            "name": "most_specific_theme_label",
            "type": "string",
            "facet": True,
            "optional": True,
        },
        {"name": "published_year", "type": "int32", "facet": True, "optional": True},
        {"name": "published_month", "type": "int32", "facet": True, "optional": True},
        {
            "name": "published_week",
            "type": "int32",
            "facet": True,
            "optional": True,
            "index": True,
        },
        {
            "name": "tags",
            "type": "string[]",
            "facet": True,
            "optional": True,
        },
        # Embedding field for semantic search (768 dimensions - BGE-M3)
        {
            "name": "content_embedding",
            "type": "float[]",
            "num_dim": 768,
            "optional": True,
            "index": True,
        },
    ],
    "default_sorting_field": "published_at",
}


def create_collection(
    client: typesense.Client,
    collection_name: str = COLLECTION_NAME,
    schema: dict[str, Any] | None = None,
) -> bool:
    """
    Cria a coleção de notícias com o schema apropriado.

    Args:
        client: Cliente Typesense
        collection_name: Nome da coleção (default: 'news')
        schema: Schema customizado (default: COLLECTION_SCHEMA)

    Returns:
        True se a coleção foi criada ou já existe

    Raises:
        Exception: Se ocorrer erro na criação
    """
    try:
        try:
            client.collections[collection_name].retrieve()
            logger.info(f"Coleção '{collection_name}' já existe")
            return True
        except ObjectNotFound:
            logger.info(f"Coleção '{collection_name}' não encontrada, criando nova")

        schema_to_use = schema or COLLECTION_SCHEMA.copy()
        schema_to_use["name"] = collection_name

        client.collections.create(schema_to_use)
        logger.info("Coleção criada com sucesso")
        return True

    except Exception as e:
        logger.error(f"Erro ao criar coleção: {e}")
        raise


def delete_collection(
    client: typesense.Client,
    collection_name: str = COLLECTION_NAME,
    confirm: bool = False,
    max_retries: int = 3,
) -> bool:
    """
    Deleta uma coleção do Typesense.

    Args:
        client: Cliente Typesense
        collection_name: Nome da coleção a deletar
        confirm: Se True, pula confirmação interativa
        max_retries: Número máximo de tentativas

    Returns:
        True se deletado com sucesso, False caso contrário
    """
    try:
        # Verifica se a coleção existe
        try:
            collection_info = client.collections[collection_name].retrieve()
            num_docs = collection_info.get("num_documents", 0)
            logger.info(
                f"Encontrada coleção '{collection_name}' com {num_docs} documentos"
            )
        except ObjectNotFound:
            logger.warning(f"Coleção '{collection_name}' não existe")
            return False

        # Prompt de confirmação
        if not confirm:
            logger.warning("=" * 80)
            logger.warning(
                f"ATENÇÃO: Você está prestes a deletar a coleção '{collection_name}'"
            )
            logger.warning(f"Isso removerá permanentemente {num_docs} documentos")
            logger.warning("=" * 80)
            response = input("Digite 'DELETE' para confirmar: ")
            if response != "DELETE":
                logger.info("Deleção cancelada")
                return False

        # Deleta com retry logic
        logger.info(f"Deletando coleção '{collection_name}'...")

        for attempt in range(1, max_retries + 1):
            try:
                client.collections[collection_name].delete()
                logger.info(f"Coleção '{collection_name}' deletada com sucesso")

                # Verifica deleção
                time.sleep(1)
                try:
                    client.collections[collection_name].retrieve()
                    logger.warning(
                        f"Coleção ainda existe após tentativa {attempt} de deleção"
                    )
                    if attempt < max_retries:
                        logger.info(
                            f"Tentando novamente... ({attempt + 1}/{max_retries})"
                        )
                        time.sleep(2)
                        continue
                except ObjectNotFound:
                    logger.info("Deleção verificada - coleção não existe mais")
                    return True

            except ObjectNotFound:
                logger.info("Coleção já foi deletada")
                return True
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    logger.info("Coleção já foi deletada")
                    return True
                logger.warning(f"Tentativa {attempt} falhou: {e}")
                if attempt < max_retries:
                    logger.info(
                        f"Tentando novamente em 2 segundos... ({attempt + 1}/{max_retries})"
                    )
                    time.sleep(2)
                else:
                    raise

        logger.error("Falha ao deletar coleção após todas as tentativas")
        return False

    except Exception as e:
        logger.error(f"Erro ao deletar coleção: {e}")
        return False


def list_collections(client: typesense.Client) -> list[dict[str, Any]]:
    """
    Lista todas as coleções disponíveis.

    Args:
        client: Cliente Typesense

    Returns:
        Lista de dicionários com informações das coleções
    """
    try:
        collections = client.collections.retrieve()

        logger.info("Coleções disponíveis:")
        for collection in collections:
            name = collection.get("name", "unknown")
            num_docs = collection.get("num_documents", 0)
            logger.info(f"  - {name}: {num_docs} documentos")

        return collections

    except Exception as e:
        logger.error(f"Erro ao listar coleções: {e}")
        return []
