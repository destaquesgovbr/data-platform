"""
Job de sincronização PostgreSQL → Typesense.

Este job lê notícias do PostgreSQL e indexa no Typesense,
incluindo embeddings para busca semântica.

Suporta processamento em batches para evitar estouro de memória
em datasets grandes (300k+ registros).
"""

import logging
from typing import Any

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.typesense import (
    get_client,
    create_collection,
    index_documents,
    calculate_published_week,
)

logger = logging.getLogger(__name__)

# Tamanho padrão do batch para leitura do PostgreSQL
DEFAULT_PG_BATCH_SIZE = 5000

# Tamanho padrão do batch para indexação no Typesense
DEFAULT_TS_BATCH_SIZE = 1000


def sync_to_typesense(
    start_date: str,
    end_date: str | None = None,
    full_sync: bool = False,
    batch_size: int = DEFAULT_TS_BATCH_SIZE,
    pg_batch_size: int = DEFAULT_PG_BATCH_SIZE,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Sincroniza notícias do PostgreSQL para Typesense.

    Processa dados em batches para evitar estouro de memória em datasets grandes.
    Sempre inclui embeddings na indexação.

    Args:
        start_date: Data inicial (YYYY-MM-DD)
        end_date: Data final (opcional, default: start_date)
        full_sync: Se True, força reindexação mesmo em coleção não vazia
        batch_size: Tamanho do lote para indexação no Typesense (default: 1000)
        pg_batch_size: Tamanho do lote para leitura do PostgreSQL (default: 5000)
        limit: Número máximo de registros (para testes)

    Returns:
        Dicionário com estatísticas (sempre inclui embeddings):
            - total_fetched: Total de registros lidos do PostgreSQL
            - total_processed: Total de registros processados
            - total_indexed: Total de registros indexados com sucesso
            - errors: Número de erros
            - skipped: Se a indexação foi pulada
    """
    end_date = end_date or start_date

    logger.info(
        f"Iniciando sincronização PostgreSQL → Typesense "
        f"(período: {start_date} a {end_date})"
    )

    # Conectar ao PostgreSQL
    pg_manager = PostgresManager()

    # Estatísticas globais
    stats = {
        "total_fetched": 0,
        "total_processed": 0,
        "total_indexed": 0,
        "errors": 0,
        "skipped": False,
    }

    try:
        # Conectar ao Typesense
        client = get_client()

        # Criar coleção se não existir
        create_collection(client)

        # Verificar se devemos pular (modo full sem force em coleção não vazia)
        if full_sync:
            from data_platform.typesense.collection import COLLECTION_NAME
            collection_info = client.collections[COLLECTION_NAME].retrieve()
            existing_count = collection_info.get("num_documents", 0)
            if existing_count > 0:
                logger.warning(
                    f"Modo full-sync com {existing_count} documentos existentes. "
                    "Documentos serão atualizados via upsert."
                )

        # Se temos um limit pequeno, usar método tradicional (mais simples)
        if limit and limit <= pg_batch_size:
            return _sync_small_dataset(
                pg_manager=pg_manager,
                client=client,
                start_date=start_date,
                end_date=end_date,
                full_sync=full_sync,
                batch_size=batch_size,
                limit=limit,
            )

        # Processar em batches para datasets grandes
        logger.info(
            f"Processando em batches (pg_batch={pg_batch_size}, ts_batch={batch_size})"
        )

        batch_num = 0
        for df_batch in pg_manager.iter_news_for_typesense(
            start_date=start_date,
            end_date=end_date,
            batch_size=pg_batch_size,
        ):
            batch_num += 1
            stats["total_fetched"] += len(df_batch)

            # Calcular published_week
            if "published_at_ts" in df_batch.columns:
                df_batch["published_week"] = df_batch["published_at_ts"].apply(
                    calculate_published_week
                )

            # Indexar batch no Typesense
            mode = "incremental"  # Sempre incremental em batches (upsert)
            batch_stats = index_documents(
                client=client,
                df=df_batch,
                mode=mode,
                force=True,  # Force para permitir upserts
                batch_size=batch_size,
            )

            stats["total_processed"] += batch_stats["total_processed"]
            stats["total_indexed"] += batch_stats["total_indexed"]
            stats["errors"] += batch_stats["errors"]

            logger.info(
                f"Batch {batch_num} concluído: "
                f"{batch_stats['total_indexed']} indexados, "
                f"{batch_stats['errors']} erros"
            )

            # Se atingiu o limite, parar
            if limit and stats["total_fetched"] >= limit:
                break

        logger.info(
            f"Sincronização concluída: "
            f"{stats['total_indexed']} indexados, "
            f"{stats['errors']} erros "
            f"(total: {stats['total_fetched']} registros)"
        )

        return stats

    finally:
        pg_manager.close_all()


def _sync_small_dataset(
    pg_manager: PostgresManager,
    client,
    start_date: str,
    end_date: str,
    full_sync: bool,
    batch_size: int,
    limit: int | None,
) -> dict[str, Any]:
    """
    Sincroniza datasets pequenos usando o método tradicional (tudo em memória).

    Usado quando limit é pequeno ou para datasets pequenos.
    Sempre inclui embeddings.
    """
    df = pg_manager.get_news_for_typesense(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

    if df.empty:
        logger.info("Nenhuma notícia encontrada no período")
        return {
            "total_fetched": 0,
            "total_processed": 0,
            "total_indexed": 0,
            "errors": 0,
            "skipped": False,
        }

    # Calcular published_week
    if "published_at_ts" in df.columns:
        df["published_week"] = df["published_at_ts"].apply(calculate_published_week)

    logger.info(f"Encontradas {len(df)} notícias para indexar")

    # Indexar documentos
    mode = "full" if full_sync else "incremental"
    stats = index_documents(
        client=client,
        df=df,
        mode=mode,
        force=full_sync,
        batch_size=batch_size,
    )

    stats["total_fetched"] = len(df)

    logger.info(
        f"Sincronização concluída: "
        f"{stats['total_indexed']} indexados, "
        f"{stats['errors']} erros"
    )

    return stats
