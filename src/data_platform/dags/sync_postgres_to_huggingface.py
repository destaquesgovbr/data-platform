"""
DAG para sincronizar notícias do PostgreSQL para HuggingFace.

Executa diariamente após o pipeline de scraper/enrichment.
Processa notícias do dia anterior (logical_date - 1 day).
"""

from datetime import datetime, timedelta
from collections import OrderedDict
import logging
import os

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.hooks.base import BaseHook

# Constants
DATASET_PATH = "nitaibezerra/govbrnews"
REDUCED_DATASET_PATH = "nitaibezerra/govbrnews-reduced"

# Colunas do dataset HuggingFace (ordem importante)
HF_COLUMNS = [
    "unique_id", "agency", "published_at", "updated_datetime", "extracted_at",
    "title", "subtitle", "editorial_lead", "url", "content",
    "image", "video_url", "category", "tags",
    "theme_1_level_1", "theme_1_level_1_code", "theme_1_level_1_label",
    "theme_1_level_2_code", "theme_1_level_2_label",
    "theme_1_level_3_code", "theme_1_level_3_label",
    "most_specific_theme_code", "most_specific_theme_label",
    "summary"
]


@dag(
    dag_id="sync_postgres_to_huggingface",
    description="Sincroniza notícias do PostgreSQL para HuggingFace diariamente",
    schedule="0 6 * * *",  # 6 AM UTC (após pipeline das 4 AM)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["sync", "huggingface", "postgres", "daily"],
    default_args={
        "owner": "data-platform",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
    },
)
def sync_postgres_to_huggingface_dag():
    """
    DAG que sincroniza notícias do PostgreSQL para HuggingFace.
    """

    @task
    def sync_news_to_huggingface(logical_date=None) -> dict:
        """
        Task única que:
        1. Lê notícias do dia anterior do PostgreSQL
        2. Converte para formato HuggingFace (OrderedDict)
        3. Faz push para HuggingFace Hub usando DatasetManager

        Returns:
            dict: Estatísticas do sync
        """
        from data_platform.managers.dataset_manager import DatasetManager

        # Obter data alvo (dia anterior ao logical_date)
        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        logging.info(f"Iniciando sync para data: {target_date}")

        # Configurar HF_TOKEN da connection
        hf_conn = BaseHook.get_connection('huggingface_default')
        os.environ["HF_TOKEN"] = hf_conn.password

        # Query PostgreSQL
        pg_hook = PostgresHook(postgres_conn_id="postgres_default")

        query = """
            SELECT
                n.unique_id,
                n.agency_key as agency,
                n.published_at,
                n.updated_datetime,
                n.extracted_at,
                n.title,
                n.subtitle,
                n.editorial_lead,
                n.url,
                n.content,
                n.image_url as image,
                n.video_url,
                n.category,
                n.tags,
                t1.label as theme_1_level_1,
                t1.code as theme_1_level_1_code,
                t1.label as theme_1_level_1_label,
                t2.code as theme_1_level_2_code,
                t2.label as theme_1_level_2_label,
                t3.code as theme_1_level_3_code,
                t3.label as theme_1_level_3_label,
                tm.code as most_specific_theme_code,
                tm.label as most_specific_theme_label,
                n.summary
            FROM news n
            LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
            LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
            LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
            LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
            WHERE n.published_at >= %s
              AND n.published_at < %s::date + INTERVAL '1 day'
            ORDER BY n.published_at DESC
        """

        records = pg_hook.get_records(query, parameters=[target_date, target_date])
        logging.info(f"Encontrados {len(records)} registros para {target_date}")

        if not records:
            logging.warning(f"Nenhum registro encontrado para {target_date}. Pulando sync.")
            return {
                "status": "skipped",
                "target_date": target_date,
                "records_synced": 0,
            }

        # Converter para OrderedDict (formato esperado pelo DatasetManager)
        data = OrderedDict()
        for col in HF_COLUMNS:
            data[col] = []

        for record in records:
            for i, col in enumerate(HF_COLUMNS):
                value = record[i]
                # Converter datetime para string ISO
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                data[col].append(value)

        # Push para HuggingFace usando DatasetManager
        logging.info(f"Iniciando push de {len(records)} registros para HuggingFace...")
        manager = DatasetManager()
        manager.insert(data, allow_update=True)

        logging.info("=" * 60)
        logging.info("PostgreSQL → HuggingFace Sync Concluído")
        logging.info("=" * 60)
        logging.info(f"Data processada: {target_date}")
        logging.info(f"Registros sincronizados: {len(records)}")
        logging.info(f"Dataset: {DATASET_PATH}")
        logging.info("=" * 60)

        return {
            "status": "success",
            "target_date": target_date,
            "records_synced": len(records),
            "dataset_path": DATASET_PATH,
        }

    # Executar task
    sync_news_to_huggingface()


# Instanciar DAG
dag_instance = sync_postgres_to_huggingface_dag()
