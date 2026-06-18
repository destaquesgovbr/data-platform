"""DAG: backfill da canonicalizacao de entidades (Step B) via Cloud Run Job.

Dispara o Cloud Run Job `destaquesgovbr-canon-backfill` (imagem + logica no repo
data-science). O Job percorre `entity_registry_seen` pendente, resolve cada forma
(gazetteer -> Wikidata -> LLM) e grava `canonical_id`. E resumivel e auto-limitado
pelo governador de cota (le o ledger `llm_daily_usage`, para gracioso ao atingir
BACKFILL_QUOTA_FRACTION x cota diaria do modelo).

Schedule diario as 02:00 (defasado do ner_backfill, que roda as 04:00). O governador
e o teto PRIMARIO; os args `--since`/`--limit` sao apenas guard secundario por execucao.

Espelha o padrao de generate_video_thumbnails (dispara Cloud Run) e sync_graph_to_neo4j
(import de airflow protegido + config via Variable.get com fallback).
"""

import logging
from datetime import datetime, timedelta

try:
    from airflow.decorators import dag
    from airflow.models import Variable
    from airflow.providers.google.cloud.operators.cloud_run import (
        CloudRunExecuteJobOperator,
    )
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Defaults espelham o contrato fixo da infra (Terraform):
#   - job: google_cloud_run_v2_job.canon_backfill (name destaquesgovbr-canon-backfill)
#   - region: var.region = southamerica-east1
# Em prod os valores vem das Airflow Variables (Secret Manager backend, prefixo
# airflow-variables-): canon_job_name, cloud_run_jobs_region. GCP_PROJECT_ID e env
# var do Composer (composer.tf).
DEFAULT_JOB_NAME = "destaquesgovbr-canon-backfill"
DEFAULT_REGION = "southamerica-east1"

# Janela rolante ampla: cobre o acervo. O governador de cota e o teto real; --since
# evita reprocessar fora da janela e --limit e um guard secundario por execucao.
DEFAULT_SINCE = "2018-01-01"
DEFAULT_RUN_LIMIT = "2000"


@dag(
    dag_id="canonicalize_backfill",
    description="Backfill da canonicalizacao de entidades (Step B) via Cloud Run Job, sob governador de cota",
    schedule="0 2 * * *",  # diario as 02:00 (defasado do ner_backfill as 04:00)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "entities", "canonicalization", "backfill"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=70),
    },
    doc_md="""
    ### Backfill da canonicalizacao de entidades (Step B)

    Dispara o Cloud Run Job **destaquesgovbr-canon-backfill** (logica no repo
    data-science: `canonicalization_job.py`). O Job resolve as formas pendentes em
    `entity_registry_seen` (gazetteer -> Wikidata -> LLM), grava `canonical_id` em
    `news_features` e e **resumivel**.

    **Governador de cota (teto primario):** antes de cada batch o Job soma o consumo
    do dia para o modelo no ledger `llm_daily_usage` e **para gracioso (exit 0)** ao
    atingir `BACKFILL_QUOTA_FRACTION` (0.8) da cota diaria, deixando >=20% para o
    worker ao vivo. Retomado na proxima run.

    **Args (guard secundario):** `--since` (janela rolante ampla) e `--limit`
    (teto por execucao). O grafo (`project_entity_graph`, 6h) cresce sozinho conforme
    `canonical_id` aumenta.

    Config via Airflow Variables (Secret Manager backend): `canon_job_name`,
    `cloud_run_jobs_region`, `canon_run_limit`.
    """,
)
def canonicalize_backfill():
    import os

    project_id = os.environ["GCP_PROJECT_ID"]
    region = Variable.get("cloud_run_jobs_region", default_var=DEFAULT_REGION)
    job_name = Variable.get("canon_job_name", default_var=DEFAULT_JOB_NAME)
    since = Variable.get("canon_backfill_since", default_var=DEFAULT_SINCE)
    run_limit = Variable.get("canon_run_limit", default_var=DEFAULT_RUN_LIMIT)

    # Formato do overrides conforme RunJobRequest.Overrides (proto-plus, snake_case):
    # passado direto ao hook -> RunJobRequest(overrides=...). Sobrescreve os args do
    # unico container do Job; os demais campos (env, imagem) vem do Job no Terraform.
    CloudRunExecuteJobOperator(
        task_id="run_canon_backfill",
        project_id=project_id,
        region=region,
        job_name=job_name,
        overrides={
            "container_overrides": [
                {
                    "args": ["--since", since, "--limit", run_limit],
                    "clear_args": True,
                }
            ],
        },
    )


dag_instance = canonicalize_backfill()
