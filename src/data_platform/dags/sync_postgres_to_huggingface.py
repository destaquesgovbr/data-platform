"""
DAG para sincronizar noticias do PostgreSQL para HuggingFace.

Executa diariamente apos o pipeline de scraper/enrichment.
Processa noticias do dia anterior (logical_date - 1 day).

NOTA: Esta DAG eh auto-contida e nao depende de modulos externos
do projeto data_platform para funcionar no Cloud Composer.
"""

from datetime import datetime, timedelta
from collections import OrderedDict
import logging
import os
import shutil
from pathlib import Path

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
    description="Sincroniza noticias do PostgreSQL para HuggingFace diariamente",
    schedule="0 6 * * *",  # 6 AM UTC (apos pipeline das 4 AM)
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
    DAG que sincroniza noticias do PostgreSQL para HuggingFace.
    """

    @task
    def sync_news_to_huggingface(logical_date=None) -> dict:
        """
        Task unica que:
        1. Le noticias do dia anterior do PostgreSQL
        2. Converte para formato HuggingFace (OrderedDict)
        3. Faz push para HuggingFace Hub

        Returns:
            dict: Estatisticas do sync
        """
        # Imports dentro da task para lazy loading
        import pandas as pd
        from datasets import Dataset, load_dataset
        from datasets.exceptions import DatasetNotFoundError
        from huggingface_hub import HfApi

        # Obter data alvo (dia anterior ao logical_date)
        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        logging.info(f"Iniciando sync para data: {target_date}")

        # Configurar HF_TOKEN da connection
        hf_conn = BaseHook.get_connection('huggingface_default')
        hf_token = hf_conn.password
        os.environ["HF_TOKEN"] = hf_token

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

        # Converter para OrderedDict
        new_data = OrderedDict()
        for col in HF_COLUMNS:
            new_data[col] = []

        for record in records:
            for i, col in enumerate(HF_COLUMNS):
                value = record[i]
                # Converter datetime para string ISO
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                new_data[col].append(value)

        # ==========================================
        # Logica do DatasetManager.insert() inline
        # ==========================================

        def load_existing_dataset():
            """Carrega dataset existente do HuggingFace."""
            try:
                # Limpar cache para evitar problemas de schema
                cache_dir = Path.home() / ".cache" / "huggingface" / "datasets" / DATASET_PATH.replace("/", "___")
                if cache_dir.exists():
                    logging.info(f"Limpando cache em {cache_dir}")
                    shutil.rmtree(cache_dir, ignore_errors=True)

                existing = load_dataset(DATASET_PATH, split="train", download_mode="force_redownload")
                logging.info(f"Dataset existente carregado. Linhas: {len(existing)}")
                return existing
            except DatasetNotFoundError:
                logging.info(f"Dataset nao encontrado em {DATASET_PATH}")
                return None

        def merge_data(hf_dataset, new_data, allow_update=True):
            """Merge novos dados com dataset existente."""
            df_existing = hf_dataset.to_pandas()
            df_new = pd.DataFrame(new_data)

            # Converter colunas datetime
            datetime_cols = ['published_at', 'updated_datetime', 'extracted_at']
            for col in datetime_cols:
                if col in df_new.columns:
                    df_new[col] = pd.to_datetime(df_new[col], errors='coerce')

            # Garantir mesmas colunas
            all_cols = set(df_existing.columns).union(df_new.columns)
            for col in all_cols:
                if col not in df_existing.columns:
                    df_existing[col] = None
                if col not in df_new.columns:
                    df_new[col] = None

            # Remover duplicatas
            df_existing.drop_duplicates(subset="unique_id", keep="first", inplace=True)
            df_new.drop_duplicates(subset="unique_id", keep="first", inplace=True)

            # Usar unique_id como index
            df_existing.set_index("unique_id", inplace=True)
            df_new.set_index("unique_id", inplace=True)

            if allow_update:
                # Atualizar linhas existentes
                df_existing.update(df_new)

                # Adicionar novas linhas
                missing_ids = df_new.index.difference(df_existing.index)
                if not missing_ids.empty:
                    logging.info(f"Inserindo {len(missing_ids)} novas linhas.")
                    df_existing = pd.concat([df_existing, df_new.loc[missing_ids]], axis=0)
                else:
                    logging.info("Todas as linhas ja existiam e foram atualizadas.")
            else:
                # Apenas adicionar novas
                df_filtered = df_new.loc[df_new.index.difference(df_existing.index)]
                if not df_filtered.empty:
                    logging.info(f"Adicionando {len(df_filtered)} novas linhas.")
                    df_existing = pd.concat([df_existing, df_filtered], axis=0)

            df_existing.reset_index(inplace=True)
            return Dataset.from_pandas(df_existing, preserve_index=False)

        def sort_dataset(hf_dataset):
            """Ordena dataset por agency e published_at."""
            df = hf_dataset.to_pandas()
            df.sort_values(by=["agency", "published_at"], ascending=[True, False], inplace=True)
            return Dataset.from_pandas(df, preserve_index=False)

        def push_reduced_dataset(df):
            """Cria e envia versao reduzida do dataset."""
            reduced_df = df[["published_at", "agency", "title", "url"]]
            reduced_dataset = Dataset.from_pandas(reduced_df, preserve_index=False)
            reduced_dataset.push_to_hub(REDUCED_DATASET_PATH, private=False, token=hf_token)
            logging.info(f"Dataset reduzido enviado para {REDUCED_DATASET_PATH}")

        # Executar logica de insert
        logging.info(f"Iniciando push de {len(records)} registros para HuggingFace...")

        dataset = load_existing_dataset()
        if dataset is None:
            logging.info("Criando dataset do zero...")
            dataset = Dataset.from_dict(new_data)
        else:
            dataset = merge_data(dataset, new_data, allow_update=True)

        # Ordenar
        dataset = sort_dataset(dataset)

        # Push para HuggingFace
        dataset.push_to_hub(DATASET_PATH, private=False, token=hf_token)
        logging.info(f"Dataset principal enviado para {DATASET_PATH}")

        # Push versao reduzida
        push_reduced_dataset(dataset.to_pandas())

        logging.info("=" * 60)
        logging.info("PostgreSQL -> HuggingFace Sync Concluido")
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
