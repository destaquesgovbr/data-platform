"""
DAG: Geração de thumbnails automáticos para notícias de vídeo.

Schedule: A cada 4 horas.
Busca artigos com video_url mas sem image_url e gera thumbnails
via Cloud Run thumbnail-worker.
"""

import base64
import concurrent.futures
import json
import logging
from datetime import datetime, timedelta

import requests

from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook
from airflow.models import Variable

logger = logging.getLogger(__name__)

WORKER_REQUEST_TIMEOUT = 60


def _process_one(article: dict, worker_url: str) -> tuple[str, str]:
    """Envia um artigo para o thumbnail worker. Retorna (unique_id, status).

    Args:
        article: Dict with unique_id key.
        worker_url: Base URL of the thumbnail worker.

    Returns:
        Tuple of (unique_id, status).
    """
    unique_id = article["unique_id"]
    try:
        resp = requests.post(
            f"{worker_url}/process",
            json={
                "message": {
                    "data": base64.b64encode(
                        json.dumps({"unique_id": unique_id}).encode()
                    ).decode(),
                    "attributes": {},
                }
            },
            timeout=WORKER_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return unique_id, result.get("status", "unknown")
    except Exception as e:
        logger.error(f"Erro ao processar {unique_id}: {e}")
        return unique_id, "failed"


@dag(
    dag_id="generate_video_thumbnails",
    description="Gera thumbnails automáticos para notícias de vídeo sem imagem",
    schedule="0 */4 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "thumbnail", "video"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Geração de Thumbnails para Vídeos

    Busca artigos com `video_url` mas sem `image_url` e gera thumbnails
    automaticamente, extraindo o primeiro frame do vídeo via ffmpeg.

    **Flow**: PG (batch) → Thumbnail Worker (Cloud Run) → GCS + PG

    Artigos com falha anterior (`thumbnail_failed: true`) são ignorados.
    """,
)
def generate_video_thumbnails_dag():
    @task()
    def fetch_batch():
        """Busca batch de artigos que precisam de thumbnail."""
        from data_platform.jobs.thumbnail.batch import fetch_articles_needing_thumbnails

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        engine = create_engine(db_url, poolclass=NullPool)
        try:
            batch_size = int(Variable.get("thumbnail_batch_size", default_var="100"))
            articles = fetch_articles_needing_thumbnails(engine, batch_size=batch_size)
        finally:
            engine.dispose()

        if not articles:
            logger.info("Nenhum artigo para gerar thumbnail")
            return []

        logger.info(f"Batch de thumbnails: {len(articles)} artigos")
        return articles

    @task()
    def generate_thumbnails(articles: list[dict]):
        """Envia artigos para o Thumbnail Worker via HTTP (paralelo)."""
        if not articles:
            return {"processed": 0, "generated": 0, "failed": 0, "skipped": 0}

        worker_url = Variable.get("thumbnail_worker_url")
        max_workers = int(Variable.get("thumbnail_max_workers", default_var="5"))
        summary = {"processed": 0, "generated": 0, "failed": 0, "skipped": 0}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process_one, article, worker_url): article for article in articles
            }
            for future in concurrent.futures.as_completed(futures):
                unique_id, status = future.result()
                summary[status] = summary.get(status, 0) + 1
                summary["processed"] += 1

        return summary

    @task()
    def report_results(summary: dict):
        """Loga resumo da execução."""
        logger.info(
            f"Thumbnail batch concluído: "
            f"{summary.get('processed', 0)} processados, "
            f"{summary.get('generated', 0)} gerados, "
            f"{summary.get('skipped', 0)} ignorados, "
            f"{summary.get('failed', 0)} falhas"
        )
        return summary

    batch = fetch_batch()
    summary = generate_thumbnails(batch)
    report_results(summary)


dag_instance = generate_video_thumbnails_dag()
