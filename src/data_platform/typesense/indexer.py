"""
Indexação de documentos no Typesense.
"""

import json
import logging
import struct
from typing import Any

import pandas as pd
import typesense

from data_platform.typesense.collection import COLLECTION_NAME

logger = logging.getLogger(__name__)

# Limite máximo de caracteres para uma tag válida
MAX_TAG_LENGTH = 100

# Mapeamento de tipo de entidade (news_features.features.entities) → campo Typesense.
# Tipos não listados (LAW, WORK, PRODUCT, MISC, ...) caem em entity_misc.
_ENTITY_TYPE_TO_FIELD: dict[str, str] = {
    "ORG": "entity_org",
    "PER": "entity_per",
    "LOC": "entity_loc",
    "EVENT": "entity_event",
    "POLICY": "entity_policy",
}


def _dedup_preserving_order(values: list[str]) -> list[str]:
    """Remove duplicados preservando a ordem de primeira ocorrência."""
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result


def extract_entity_fields(entities_value: Any) -> dict[str, list[str]]:
    """
    Constrói os campos de entidade do Typesense a partir da lista de entidades.

    A lista (de `news_features.features.entities`) tem o formato
    ``[{"text": str, "type": str, "count": int}, ...]``. O match é exato pelo
    texto bruto da entidade (v1, sem normalização/canonicalização).

    Args:
        entities_value: Lista de dicts de entidades (ou None / valor inválido).

    Returns:
        Dicionário com as chaves ``entities`` (todos os textos, dedup),
        ``entity_org``/``entity_per``/``entity_loc``/``entity_event``/
        ``entity_policy``/``entity_misc`` (por tipo) e ``entity_canonical``
        (lista ordenada e única de ``canonical_id`` não-nulos das menções).
        Chaves com lista vazia são omitidas para não popular campos sem dado.
    """
    # JSONB pode chegar como string (dependendo do driver/adaptador); tenta parsear.
    if isinstance(entities_value, str):
        try:
            entities_value = json.loads(entities_value)
        except json.JSONDecodeError:
            return {}

    if not isinstance(entities_value, list):
        return {}

    buckets: dict[str, list[str]] = {
        "entity_org": [],
        "entity_per": [],
        "entity_loc": [],
        "entity_event": [],
        "entity_policy": [],
        "entity_misc": [],
    }
    all_texts: list[str] = []
    canonical_ids: set[str] = set()

    for entity in entities_value:
        if not isinstance(entity, dict):
            continue
        text = entity.get("text")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue

        entity_type = entity.get("type")
        entity_type = entity_type.strip().upper() if isinstance(entity_type, str) else ""
        field = _ENTITY_TYPE_TO_FIELD.get(entity_type, "entity_misc")

        buckets[field].append(text)
        all_texts.append(text)

        canonical_id = entity.get("canonical_id")
        if isinstance(canonical_id, str) and canonical_id.strip():
            canonical_ids.add(canonical_id.strip())

    result: dict[str, list[str]] = {}
    combined = _dedup_preserving_order(all_texts)
    if combined:
        result["entities"] = combined
    for field, texts in buckets.items():
        deduped = _dedup_preserving_order(texts)
        if deduped:
            result[field] = deduped
    if canonical_ids:
        result["entity_canonical"] = sorted(canonical_ids)

    return result


def clean_tags(tags_value) -> list[str]:
    """
    Limpa e normaliza o campo tags.

    Args:
        tags_value: Valor do campo tags (pode ser numpy.ndarray, list ou None)

    Returns:
        Lista de tags limpas e válidas
    """
    # Converter numpy.ndarray para list
    if hasattr(tags_value, "tolist"):
        tags = tags_value.tolist()
    elif isinstance(tags_value, list):
        tags = tags_value
    else:
        return []

    # Filtrar e limpar
    cleaned = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        # Ignorar tags vazias
        if not tag:
            continue
        # Ignorar tags muito longas (provavelmente são textos, não tags)
        if len(tag) > MAX_TAG_LENGTH:
            continue
        cleaned.append(tag)

    return cleaned


def parse_embedding(embedding_value) -> list[float] | None:
    """
    Converte embedding do PostgreSQL (pgvector) para lista de floats.

    Args:
        embedding_value: Valor do embedding (pode ser string, bytes, memoryview ou list)

    Returns:
        Lista de floats ou None se inválido
    """
    if embedding_value is None:
        return None

    if isinstance(embedding_value, list):
        # Already a list
        return embedding_value

    if isinstance(embedding_value, str):
        # Parse string representation like '[1.0, 2.0, ...]'
        try:
            return json.loads(embedding_value)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse embedding string: {embedding_value[:50]}...")
            return None

    if isinstance(embedding_value, (bytes, memoryview)):
        # Convert bytes to list of floats (pgvector binary format)
        try:
            data = bytes(embedding_value)
            # pgvector binary format: dimension (2 bytes) + floats (4 bytes each)
            dim = struct.unpack("!H", data[:2])[0]
            return list(struct.unpack(f"!{dim}f", data[2:]))
        except Exception as e:
            logger.warning(f"Failed to parse embedding bytes: {e}")
            return None

    logger.warning(f"Unknown embedding type: {type(embedding_value)}")
    return None


def prepare_document(row: pd.Series) -> dict[str, Any]:
    """
    Prepara um documento para indexação no Typesense.

    Args:
        row: Linha do DataFrame com dados do documento

    Returns:
        Dicionário formatado para o Typesense
    """
    # Usa unique_id como id do documento para comportamento de upsert
    unique_id = (
        str(row["unique_id"]) if pd.notna(row["unique_id"]) else f"doc_{row.name}"
    )

    doc: dict[str, Any] = {
        "id": unique_id,  # Typesense usa 'id' como chave primária para upsert
        "unique_id": unique_id,  # Mantém para compatibilidade
        # published_at é obrigatório (campo de ordenação padrão)
        "published_at": (
            int(row["published_at_ts"])
            if pd.notna(row.get("published_at_ts")) and row["published_at_ts"] > 0
            else 0
        ),
    }

    # Adiciona campos opcionais apenas se tiverem valores válidos
    optional_string_fields = [
        "agency",
        "title",
        "url",
        "image",
        "video_url",
        "category",
        "content",
        "summary",
        "subtitle",
        "editorial_lead",
        "theme_1_level_1_code",
        "theme_1_level_1_label",
        "theme_1_level_2_code",
        "theme_1_level_2_label",
        "theme_1_level_3_code",
        "theme_1_level_3_label",
        "most_specific_theme_code",
        "most_specific_theme_label",
    ]

    for field in optional_string_fields:
        if pd.notna(row.get(field)):
            val = str(row[field]).strip()
            if val:
                doc[field] = val

    # Campos numéricos opcionais
    if pd.notna(row.get("extracted_at_ts")) and row["extracted_at_ts"] > 0:
        doc["extracted_at"] = int(row["extracted_at_ts"])

    if pd.notna(row.get("published_year")) and row["published_year"] > 0:
        doc["published_year"] = int(row["published_year"])

    if pd.notna(row.get("published_month")) and row["published_month"] > 0:
        doc["published_month"] = int(row["published_month"])

    if pd.notna(row.get("published_week")) and row["published_week"] > 0:
        doc["published_week"] = int(row["published_week"])

    # Campo tags (array de strings)
    if "tags" in row and row["tags"] is not None:
        cleaned_tags = clean_tags(row["tags"])
        if cleaned_tags:  # Só adiciona se houver tags válidas
            doc["tags"] = cleaned_tags

    # content_hash for cross-agency deduplication (group_by)
    if pd.notna(row.get("content_hash")):
        val = str(row["content_hash"]).strip()
        if val:
            doc["content_hash"] = val

    # Feature fields (optional, from news_features JOIN)
    feature_fields = [
        ("sentiment_label", str),
        ("sentiment_score", float),
        ("trending_score", float),
        ("word_count", int),
        ("has_image", bool),
        ("has_video", bool),
        ("readability_flesch", float),
    ]
    for field_name, field_type in feature_fields:
        val = row.get(field_name)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            doc[field_name] = field_type(val)

    # view_count (engagement, de news_features.features.view_count)
    view_count = row.get("view_count")
    if view_count is not None and not (isinstance(view_count, float) and pd.isna(view_count)):
        doc["view_count"] = int(view_count)

    # Entidades nomeadas (de news_features.features.entities)
    # Usa `in` + acesso direto para evitar o ValueError de pd.notna() sobre listas.
    if "entities" in row and row["entities"] is not None:
        for field_name, values in extract_entity_fields(row["entities"]).items():
            doc[field_name] = values

    # Campo de embedding (vetor de floats para busca semântica)
    if "content_embedding" in row and row["content_embedding"] is not None:
        embedding = parse_embedding(row["content_embedding"])
        if embedding:
            doc["content_embedding"] = embedding

    return doc


def index_documents(
    client: typesense.Client,
    df: pd.DataFrame,
    collection_name: str = COLLECTION_NAME,
    mode: str = "full",
    force: bool = False,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """
    Indexa os documentos do DataFrame no Typesense.

    Args:
        client: Cliente Typesense
        df: DataFrame com documentos a indexar
        collection_name: Nome da coleção
        mode: 'full' ou 'incremental'
        force: Se True, permite modo full em coleções não vazias
        batch_size: Tamanho do batch para importação (default: 1000)

    Returns:
        Dicionário com estatísticas da indexação

    Raises:
        Exception: Se ocorrer erro na indexação
    """
    stats = {
        "total_processed": 0,
        "total_indexed": 0,
        "errors": 0,
        "skipped": False,
    }

    try:
        logger.info(
            f"Indexando documentos no Typesense (modo: {mode}, force: {force})..."
        )

        # Verifica documentos existentes na coleção
        collection_info = client.collections[collection_name].retrieve()
        existing_count = collection_info.get("num_documents", 0)

        if existing_count > 0:
            logger.info(f"Coleção já contém {existing_count} documentos")
            if mode == "full":
                if force:
                    logger.warning(
                        "Modo force ativado: Documentos existentes serão sobrescritos"
                    )
                    logger.warning(
                        f"{existing_count} documentos existentes serão substituídos"
                    )
                else:
                    logger.info(
                        "Modo full em coleção não vazia. Use modo 'incremental' para atualizar."
                    )
                    logger.info(
                        "Ou use --force para sobrescrever dados existentes."
                    )
                    logger.info("Pulando indexação para evitar duplicados.")
                    stats["skipped"] = True
                    return stats
            else:
                logger.info(f"Modo incremental: {len(df)} documentos serão atualizados")

        # DataFrame vazio
        if len(df) == 0:
            logger.info("Nenhum documento para indexar. Saindo.")
            return stats

        # Prepara e indexa documentos em batches
        documents: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            try:
                doc = prepare_document(row)
                documents.append(doc)
                stats["total_processed"] += 1

                # Indexa em batches
                if len(documents) >= batch_size:
                    logger.info(
                        f"Indexando batch de {len(documents)} documentos... "
                        f"(total processado: {stats['total_processed']})"
                    )
                    result = client.collections[collection_name].documents.import_(
                        documents, {"action": "upsert"}
                    )

                    # Verifica erros
                    errors = [item for item in result if not item.get("success")]
                    if errors:
                        stats["errors"] += len(errors)
                        logger.warning(f"Encontrados {len(errors)} erros no batch")
                        for error in errors[:5]:
                            logger.warning(f"Erro: {error}")
                    else:
                        stats["total_indexed"] += len(documents)

                    documents = []

            except Exception as e:
                logger.warning(f"Erro ao preparar documento no índice {idx}: {e}")
                stats["errors"] += 1
                continue

        # Indexa documentos restantes
        if documents:
            logger.info(f"Indexando batch final de {len(documents)} documentos...")
            result = client.collections[collection_name].documents.import_(
                documents, {"action": "upsert"}
            )

            errors = [item for item in result if not item.get("success")]
            if errors:
                stats["errors"] += len(errors)
                logger.warning(f"Encontrados {len(errors)} erros no batch final")
            else:
                stats["total_indexed"] += len(documents)

        # Estatísticas finais
        collection_info = client.collections[collection_name].retrieve()
        total_docs = collection_info.get("num_documents", 0)

        logger.info("Documentos indexados com sucesso no Typesense")
        logger.info(f"Total de documentos na coleção: {total_docs}")
        logger.info("Estatísticas da coleção:")
        logger.info(f"  Total de registros: {total_docs}")
        logger.info(f"  Nome da coleção: {collection_name}")
        logger.info(f"  Campos no schema: {len(collection_info['fields'])}")

        return stats

    except Exception as e:
        logger.error(f"Erro ao indexar documentos: {e}")
        raise


def run_test_queries(
    client: typesense.Client, collection_name: str = COLLECTION_NAME
) -> None:
    """
    Executa consultas de teste para verificar a funcionalidade.

    Args:
        client: Cliente Typesense
        collection_name: Nome da coleção
    """
    try:
        logger.info("Executando consultas de teste...")

        # Teste 1: Info da coleção
        collection_info = client.collections[collection_name].retrieve()
        logger.info(f"Coleção tem {collection_info['num_documents']} documentos")

        # Teste 2: Busca simples
        search_params = {"q": "saúde", "query_by": "title,content", "limit": 3}
        results = client.collections[collection_name].documents.search(search_params)
        logger.info(f"Busca retornou {results['found']} resultados para 'saúde'")

        # Teste 3: Busca com facets
        search_params = {
            "q": "*",
            "query_by": "title",
            "facet_by": "agency",
            "max_facet_values": 5,
            "limit": 0,
        }
        results = client.collections[collection_name].documents.search(search_params)
        if results.get("facet_counts"):
            logger.info("Top agências por número de documentos:")
            for facet in results["facet_counts"][0]["counts"][:5]:
                logger.info(f"   {facet['value']}: {facet['count']} documentos")

    except Exception as e:
        logger.warning(f"Consultas de teste encontraram um problema: {e}")
