"""
DAG para sincronizar noticias do PostgreSQL para HuggingFace.

Executa diariamente apos o pipeline de scraper/enrichment.
Processa noticias do dia anterior (logical_date - 1 day).

ABORDAGEM: Append incremental via parquet shards
- Consulta IDs existentes via Dataset Viewer API (sem baixar dataset)
- Cria parquet shard com novos registros
- Upload direto via huggingface_hub

Memoria: ~10MB (apenas novos registros) vs ~1-2GB (dataset completo)
"""

from datetime import datetime, timedelta, timezone
import logging
import os
import tempfile

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.hooks.base import BaseHook

# Timezone do Brasil (UTC-3) - usado nos arquivos base do dataset
BRT = timezone(timedelta(hours=-3))

# Constants
DATASET_PATH = "nitaibezerra/govbrnews"
REDUCED_DATASET_PATH = "nitaibezerra/govbrnews-reduced"
HF_API_BASE = "https://datasets-server.huggingface.co"

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

    Usa abordagem incremental via parquet shards para evitar OOM.
    """

    @task
    def sync_news_to_huggingface(logical_date=None) -> dict:
        """
        Task que sincroniza noticias do PostgreSQL para HuggingFace.

        Abordagem:
        1. Le noticias do dia anterior do PostgreSQL
        2. Consulta IDs existentes via HuggingFace API (sem baixar dataset)
        3. Filtra apenas novos registros
        4. Cria parquet shard e faz upload

        Returns:
            dict: Estatisticas do sync
        """
        # Imports dentro da task para lazy loading
        import requests
        import pyarrow as pa
        import pyarrow.parquet as pq
        from huggingface_hub import HfApi

        # Obter data alvo (dia anterior ao logical_date)
        if logical_date is None:
            logical_date = datetime.now(timezone.utc)
            logging.info("Execucao manual detectada - usando data atual como logical_date")
        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        logging.info(f"Iniciando sync para data: {target_date}")

        # Configurar HF_TOKEN da connection
        hf_conn = BaseHook.get_connection('huggingface_default')
        hf_token = hf_conn.password

        # ==========================================
        # 1. Query PostgreSQL
        # ==========================================
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
        logging.info(f"Encontrados {len(records)} registros no PostgreSQL para {target_date}")

        if not records:
            logging.warning(f"Nenhum registro encontrado para {target_date}. Pulando sync.")
            return {
                "status": "skipped",
                "target_date": target_date,
                "records_from_pg": 0,
                "records_synced": 0,
            }

        # Converter records para lista de dicts
        # IMPORTANTE: Manter timestamps como objetos datetime para compatibilidade
        # com o schema dos arquivos base do dataset HuggingFace
        new_records = []
        for record in records:
            row = {}
            for i, col in enumerate(HF_COLUMNS):
                value = record[i]
                # Converter timestamps para o formato correto do schema base:
                # - published_at e updated_datetime: timestamp[us, tz=-03:00]
                # - extracted_at: timestamp[ns] (naive, sem timezone)
                if col in ('published_at', 'updated_datetime'):
                    if value is not None and hasattr(value, 'astimezone'):
                        # Converter para timezone -03:00 (BRT)
                        value = value.astimezone(BRT)
                elif col == 'extracted_at':
                    if value is not None and hasattr(value, 'replace'):
                        # Converter para naive (sem timezone)
                        if hasattr(value, 'tzinfo') and value.tzinfo is not None:
                            value = value.astimezone(timezone.utc).replace(tzinfo=None)
                row[col] = value
            new_records.append(row)

        # ==========================================
        # 2. Consultar IDs existentes via API
        # ==========================================
        def get_existing_ids_for_date(date_str: str) -> set:
            """Consulta unique_ids do dia via Dataset Viewer API."""
            existing_ids = set()
            offset = 0
            max_iterations = 100  # Safety limit

            logging.info(f"Consultando IDs existentes para {date_str} via API...")

            for _ in range(max_iterations):
                try:
                    url = f"{HF_API_BASE}/filter"
                    params = {
                        "dataset": DATASET_PATH,
                        "config": "default",
                        "split": "train",
                        "where": f"\"published_at\">'{date_str}T00:00:00' AND \"published_at\"<'{date_str}T23:59:59'",
                        "offset": offset,
                        "length": 100,
                    }
                    resp = requests.get(url, params=params, timeout=30)

                    if resp.status_code != 200:
                        logging.warning(f"API retornou status {resp.status_code}: {resp.text[:200]}")
                        break

                    data = resp.json()

                    if "error" in data:
                        logging.warning(f"API retornou erro: {data['error']}")
                        # Se o índice está carregando, continuar sem dedup
                        break

                    rows = data.get("rows", [])
                    if not rows:
                        break

                    for row in rows:
                        existing_ids.add(row["row"]["unique_id"])

                    offset += 100
                    if len(rows) < 100:
                        break

                except requests.RequestException as e:
                    logging.warning(f"Erro ao consultar API: {e}")
                    break

            logging.info(f"Encontrados {len(existing_ids)} IDs existentes no HuggingFace para {date_str}")
            return existing_ids

        existing_ids = get_existing_ids_for_date(target_date)

        # ==========================================
        # 3. Filtrar apenas novos registros
        # ==========================================
        new_only = [r for r in new_records if r["unique_id"] not in existing_ids]

        if not new_only:
            logging.info(f"Todos os {len(new_records)} registros ja existem no HuggingFace. Pulando sync.")
            return {
                "status": "skipped",
                "target_date": target_date,
                "records_from_pg": len(records),
                "records_already_exist": len(existing_ids),
                "records_synced": 0,
            }

        logging.info(f"Novos registros a sincronizar: {len(new_only)} de {len(new_records)}")

        # ==========================================
        # 4. Criar parquet shard
        # ==========================================
        # Preparar dados para PyArrow
        data_dict = {col: [] for col in HF_COLUMNS}
        for row in new_only:
            for col in HF_COLUMNS:
                data_dict[col].append(row.get(col))

        # Criar schema PyArrow compativel com arquivos base do dataset
        # IMPORTANTE: Os tipos de timestamp devem corresponder ao schema existente:
        # - published_at: timestamp[us, tz=-03:00]
        # - updated_datetime: timestamp[us, tz=-03:00]
        # - extracted_at: timestamp[ns] (naive, sem timezone)
        schema = pa.schema([
            ("unique_id", pa.string()),
            ("agency", pa.string()),
            ("published_at", pa.timestamp('us', tz='-03:00')),
            ("updated_datetime", pa.timestamp('us', tz='-03:00')),
            ("extracted_at", pa.timestamp('ns')),
            ("title", pa.string()),
            ("subtitle", pa.string()),
            ("editorial_lead", pa.string()),
            ("url", pa.string()),
            ("content", pa.string()),
            ("image", pa.string()),
            ("video_url", pa.string()),
            ("category", pa.string()),
            ("tags", pa.list_(pa.string())),
            ("theme_1_level_1", pa.string()),
            ("theme_1_level_1_code", pa.string()),
            ("theme_1_level_1_label", pa.string()),
            ("theme_1_level_2_code", pa.string()),
            ("theme_1_level_2_label", pa.string()),
            ("theme_1_level_3_code", pa.string()),
            ("theme_1_level_3_label", pa.string()),
            ("most_specific_theme_code", pa.string()),
            ("most_specific_theme_label", pa.string()),
            ("summary", pa.string()),
        ])

        table = pa.table(data_dict, schema=schema)

        # Salvar em arquivo temporário
        timestamp = datetime.now(timezone.utc).strftime('%H%M%S')
        shard_name = f"data/train-{target_date}-{timestamp}.parquet"

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            local_path = tmp.name
            pq.write_table(table, local_path, compression='snappy')
            logging.info(f"Parquet shard criado: {local_path}")

        # ==========================================
        # 5. Upload para HuggingFace
        # ==========================================
        api = HfApi(token=hf_token)

        try:
            api.upload_file(
                path_or_fileobj=local_path,
                path_in_repo=shard_name,
                repo_id=DATASET_PATH,
                repo_type="dataset",
                commit_message=f"Add {len(new_only)} news from {target_date}",
            )
            logging.info(f"Parquet shard enviado: {shard_name}")
        finally:
            # Limpar arquivo temporário
            os.unlink(local_path)

        # ==========================================
        # 6. Atualizar dataset reduzido
        # ==========================================
        # Criar versao reduzida (apenas colunas essenciais)
        reduced_data = {
            "published_at": data_dict["published_at"],
            "agency": data_dict["agency"],
            "title": data_dict["title"],
            "url": data_dict["url"],
        }
        reduced_schema = pa.schema([
            ("published_at", pa.timestamp('us', tz='-03:00')),
            ("agency", pa.string()),
            ("title", pa.string()),
            ("url", pa.string()),
        ])
        reduced_table = pa.table(reduced_data, schema=reduced_schema)

        reduced_shard_name = f"data/train-{target_date}-{timestamp}.parquet"
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
            reduced_path = tmp.name
            pq.write_table(reduced_table, reduced_path, compression='snappy')

        try:
            api.upload_file(
                path_or_fileobj=reduced_path,
                path_in_repo=reduced_shard_name,
                repo_id=REDUCED_DATASET_PATH,
                repo_type="dataset",
                commit_message=f"Add {len(new_only)} news from {target_date}",
            )
            logging.info(f"Dataset reduzido atualizado: {reduced_shard_name}")
        finally:
            os.unlink(reduced_path)

        # ==========================================
        # 7. Log final
        # ==========================================
        logging.info("=" * 60)
        logging.info("PostgreSQL -> HuggingFace Sync Concluido")
        logging.info("=" * 60)
        logging.info(f"Data processada: {target_date}")
        logging.info(f"Registros do PostgreSQL: {len(records)}")
        logging.info(f"Registros ja existentes: {len(existing_ids)}")
        logging.info(f"Registros sincronizados: {len(new_only)}")
        logging.info(f"Shard: {shard_name}")
        logging.info("=" * 60)

        return {
            "status": "success",
            "target_date": target_date,
            "records_from_pg": len(records),
            "records_already_exist": len(existing_ids),
            "records_synced": len(new_only),
            "shard_name": shard_name,
            "dataset_path": DATASET_PATH,
        }

    # Executar task
    sync_news_to_huggingface()


# Instanciar DAG
dag_instance = sync_postgres_to_huggingface_dag()
