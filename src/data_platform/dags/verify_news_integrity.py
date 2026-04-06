"""
DAG: Verificação de integridade de notícias.

Schedule: A cada 30 minutos.
Verifica imagens quebradas e mudanças de conteúdo em notícias raspadas,
delegando o trabalho HTTP para o Scraper Cloud Run via POST /verify/integrity.
"""

import logging
from datetime import datetime, timedelta

import requests
from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook
from airflow.models import Variable

logger = logging.getLogger(__name__)

SCRAPER_REQUEST_TIMEOUT = 120  # 2 min para o batch completo


@dag(
    dag_id="verify_news_integrity",
    description="Verifica integridade de imagens e conteúdo das notícias",
    schedule="*/30 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "integrity", "quality"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=3),
        "execution_timeout": timedelta(minutes=25),
    },
    doc_md="""
    ### Verificação de Integridade de Notícias

    Verifica periodicamente se imagens e conteúdo das notícias raspadas ainda
    estão disponíveis nas fontes originais (gov.br).

    **Flow**: PG (batch priorizado) → Scraper Cloud Run (HTTP checks) → PG (news_features) → Typesense

    **Priorização**: Artigos recentes são verificados com mais frequência.
    - < 3h: a cada 10 min
    - 3-24h: a cada 1h
    - 1-7 dias: a cada 6h
    - 7-30 dias: a cada 24h
    - 1-5 meses: a cada 7 dias
    """,
)
def verify_news_integrity_dag():

    @task()
    def fetch_batch(**context):
        """Busca batch priorizado de artigos para verificação."""
        from data_platform.jobs.integrity.priority import fetch_priority_batch

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        batch_size = int(Variable.get("integrity_batch_size", default_var="400"))
        articles = fetch_priority_batch(db_url, batch_size=batch_size)

        if not articles:
            logger.info("Nenhum artigo para verificar")
            return []

        logger.info(f"Batch de verificação: {len(articles)} artigos")
        return articles

    @task()
    def call_scraper(articles: list[dict]):
        """Envia batch para o Scraper Cloud Run verificar."""
        if not articles:
            return {"results": [], "summary": {"total": 0}}

        scraper_url = Variable.get("scraper_api_url")
        url = f"{scraper_url}/verify/integrity"

        logger.info(f"Enviando {len(articles)} artigos para {url}")
        resp = requests.post(
            url,
            json={"articles": articles},
            timeout=SCRAPER_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        data = resp.json()
        summary = data.get("summary", {})
        logger.info(
            f"Resultado: {summary.get('total', 0)} verificados, "
            f"{summary.get('images_broken', 0)} imagens quebradas, "
            f"{summary.get('content_changed', 0)} conteúdos alterados"
        )
        return data

    @task()
    def save_results(data: dict):
        """Persiste resultados no news_features."""
        from data_platform.jobs.integrity.results import upsert_integrity_results

        results = data.get("results", [])
        if not results:
            return {"broken_ids": [], "fixed_ids": [], "count": 0}

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        return upsert_integrity_results(db_url, results)

    @task()
    def sync_typesense(changes: dict):
        """Atualiza campo image_broken no Typesense para artigos afetados."""
        from data_platform.jobs.integrity.results import sync_image_status_to_typesense
        from data_platform.typesense.client import get_client
        from data_platform.typesense.collection import COLLECTION_NAME

        broken_ids = changes.get("broken_ids", [])
        fixed_ids = changes.get("fixed_ids", [])

        if not broken_ids and not fixed_ids:
            logger.info("Nenhuma mudança de status de imagem para sincronizar")
            return 0

        client = get_client()
        return sync_image_status_to_typesense(client, COLLECTION_NAME, broken_ids, fixed_ids)

    batch = fetch_batch()
    data = call_scraper(batch)
    changes = save_results(data)
    sync_typesense(changes)


dag_instance = verify_news_integrity_dag()
