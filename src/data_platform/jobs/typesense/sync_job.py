"""
Job de sincronização PostgreSQL → Typesense.

Este job lê notícias do PostgreSQL e indexa no Typesense,
incluindo embeddings para busca semântica.
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


def sync_to_typesense(
    start_date: str,
    end_date: str | None = None,
    full_sync: bool = False,
    batch_size: int = 1000,
    include_embeddings: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Sincroniza notícias do PostgreSQL para Typesense.

    Args:
        start_date: Data inicial (YYYY-MM-DD)
        end_date: Data final (opcional, default: start_date)
        full_sync: Se True, força reindexação mesmo em coleção não vazia
        batch_size: Tamanho do lote para indexação
        include_embeddings: Se True, inclui embeddings na indexação
        limit: Número máximo de registros (para testes)

    Returns:
        Dicionário com estatísticas:
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

    # Conectar ao PostgreSQL e buscar dados
    pg_manager = PostgresManager()

    try:
        # Buscar notícias com temas e embeddings
        df = pg_manager.get_news_for_typesense(
            start_date=start_date,
            end_date=end_date,
            include_embeddings=include_embeddings,
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

        # Conectar ao Typesense
        client = get_client()

        # Criar coleção se não existir
        create_collection(client)

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

    finally:
        pg_manager.close_all()
