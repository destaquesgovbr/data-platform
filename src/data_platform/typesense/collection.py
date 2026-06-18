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
        {"name": "video_url", "type": "string", "facet": False, "optional": True},
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
        # Deduplication
        {"name": "content_hash", "type": "string", "facet": True, "optional": True},
        # Feature fields (from news_features JSONB)
        {"name": "sentiment_label", "type": "string", "facet": True, "optional": True},
        {"name": "sentiment_score", "type": "float", "facet": False, "optional": True},
        {"name": "trending_score", "type": "float", "facet": False, "optional": True, "sort": True},
        {"name": "word_count", "type": "int32", "facet": False, "optional": True},
        {"name": "has_image", "type": "bool", "facet": True, "optional": True},
        {"name": "has_video", "type": "bool", "facet": True, "optional": True},
        {"name": "image_broken", "type": "bool", "facet": True, "optional": True},
        {"name": "readability_flesch", "type": "float", "facet": False, "optional": True},
        # Named entities (from news_features.features.entities:
        # [{text, type, count, canonical_id}]).
        # `entities` carries all entity texts (any type); `entity_*` are per-type buckets.
        # `entity_canonical` carries the deduped canonical_id list for facet-by-canonical.
        {"name": "entities", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_org", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_per", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_loc", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_event", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_policy", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_misc", "type": "string[]", "facet": True, "optional": True},
        {"name": "entity_canonical", "type": "string[]", "facet": True, "optional": True},
        # Engagement (from news_features.features.view_count)
        {"name": "view_count", "type": "int32", "facet": False, "optional": True, "sort": True},
        # Embedding fields for semantic search (dual during migration)
        # Legacy: 768-dim mpnet (will be removed after migration)
        {
            "name": "content_embedding_legacy",
            "type": "float[]",
            "num_dim": 768,
            "optional": True,
            "index": True,
        },
        # Current: 1024-dim BGE-M3 (primary embedding)
        {
            "name": "content_embedding",
            "type": "float[]",
            "num_dim": 1024,
            "optional": True,
            "index": True,
        },
        # Model version tracking
        {
            "name": "embedding_model_version",
            "type": "string",
            "facet": True,
            "optional": True,
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


_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2


def _sanitize_error(e: Exception) -> str:
    """Remove detalhes sensíveis de mensagens de erro."""
    msg = str(e)
    sensitive_keywords = ["api_key", "apikey", "token", "password", "secret"]
    if any(kw in msg.lower() for kw in sensitive_keywords):
        return f"{type(e).__name__}: [details omitted for security]"
    return msg


def update_schema(
    client: typesense.Client,
    collection_name: str = COLLECTION_NAME,
    schema: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Atualiza o schema de uma coleção existente, adicionando campos faltantes.

    Compara o schema desejado (código) com o schema live (Typesense) e adiciona
    campos que existem no código mas não na coleção via PATCH atômico.

    Comportamento:
    - Não remove campos que existem apenas no Typesense (safe)
    - Não altera definição de campos existentes (type, facet, etc.)
    - Apenas adiciona campos novos com base no nome
    - Campos existentes nos documentos não são populados automaticamente
      (rodar sync após update para popular valores)

    Args:
        client: Cliente Typesense
        collection_name: Nome da coleção
        schema: Schema desejado (default: COLLECTION_SCHEMA)
        dry_run: Se True, apenas reporta diferenças sem aplicar

    Returns:
        Dicionário com resultado:
            - added: lista de nomes de campos adicionados
            - already_exists: lista de campos que já existiam
            - errors: lista de erros (campo + mensagem)
    """
    schema_to_use = schema or COLLECTION_SCHEMA
    desired_fields = {f["name"]: f for f in schema_to_use["fields"]}

    result: dict[str, Any] = {"added": [], "already_exists": [], "errors": []}

    try:
        collection_info = client.collections[collection_name].retrieve()
    except ObjectNotFound:
        raise ValueError(
            f"Coleção '{collection_name}' não encontrada. "
            "Use create_collection() para criar uma nova."
        )

    live_field_names = {f["name"] for f in collection_info.get("fields", [])}

    missing_fields = []
    for name, field_def in desired_fields.items():
        if name in live_field_names:
            result["already_exists"].append(name)
        else:
            missing_fields.append(field_def)

    if not missing_fields:
        logger.info("Schema está atualizado — nenhum campo faltante")
        return result

    logger.info(
        f"Encontrados {len(missing_fields)} campo(s) faltante(s): "
        f"{[f['name'] for f in missing_fields]}"
    )

    if dry_run:
        result["added"] = [f["name"] for f in missing_fields]
        logger.info("[DRY-RUN] Nenhuma alteração aplicada")
        return result

    # Batch update — adiciona todos os campos em uma única chamada PATCH (atômico)
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            client.collections[collection_name].update({"fields": missing_fields})
            result["added"] = [f["name"] for f in missing_fields]
            for f in missing_fields:
                logger.info(f"  + Campo '{f['name']}' adicionado")
            break
        except Exception as e:
            error_msg = _sanitize_error(e)
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY ** attempt
                logger.warning(
                    f"Tentativa {attempt}/{_MAX_RETRIES} falhou: {error_msg}. "
                    f"Retentando em {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"Falha após {_MAX_RETRIES} tentativas: {error_msg}"
                )
                for f in missing_fields:
                    result["errors"].append(
                        {"field": f["name"], "error": error_msg}
                    )

    logger.info(
        f"Schema update concluído: {len(result['added'])} adicionados, "
        f"{len(result['errors'])} erros"
    )
    return result


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
