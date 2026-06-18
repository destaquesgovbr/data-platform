"""DAG: backfill do NER historico (~314k artigos sem NER) via Cloud Run Job.

Dispara o Cloud Run Job `destaquesgovbr-ner-backfill` (imagem + logica no repo
data-science: `backfill_ner_corpus.py`). O Job seleciona `news` SEM `news_llm_raw`
task='ner' prompt_version='ner-v1', roda o NER (Sonnet 4.6), grava entidades em
`news_features` e popula `entity_registry_seen`. E resumivel e auto-limitado pelo
governador de cota (ledger `llm_daily_usage`, para gracioso ao atingir
BACKFILL_QUOTA_FRACTION x cota diaria).

Schedule diario as 04:00 (defasado do canonicalize_backfill, que roda as 02:00).
Ordem `asc` por padrao: processa primeiro o acervo mais antigo (nunca NERado).
O governador e o teto PRIMARIO; `--limit` e apenas guard secundario por execucao.
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
#   - job: google_cloud_run_v2_job.ner_backfill (name destaquesgovbr-ner-backfill)
#   - region: var.region = southamerica-east1
# Em prod os valores vem das Airflow Variables (Secret Manager backend, prefixo
# airflow-variables-): ner_job_name, cloud_run_jobs_region. GCP_PROJECT_ID e env
# var do Composer (composer.tf).
DEFAULT_JOB_NAME = "destaquesgovbr-ner-backfill"
DEFAULT_REGION = "southamerica-east1"

# --limit e guard secundario por execucao (governador de cota e o teto real).
# --order asc processa primeiro o acervo mais antigo (nunca NERado).
DEFAULT_RUN_LIMIT = "2000"
DEFAULT_ORDER = "desc"


@dag(
    dag_id="ner_backfill",
    description="Backfill do NER historico (~314k artigos) via Cloud Run Job, sob governador de cota",
    schedule="0 4 * * *",  # diario as 04:00 (defasado do canonicalize_backfill as 02:00)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "entities", "ner", "backfill"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=70),
    },
    doc_md="""
    ### Backfill do NER historico (~314k artigos sem NER)

    Dispara o Cloud Run Job **destaquesgovbr-ner-backfill** (logica no repo
    data-science: `backfill_ner_corpus.py`). O Job seleciona `news` SEM `news_llm_raw`
    task='ner' prompt_version='ner-v1', roda o NER (Sonnet 4.6), grava entidades em
    `news_features` e popula `entity_registry_seen` (insumo do canonicalize_backfill).
    E **resumivel**.

    **Governador de cota (teto primario):** antes de cada batch o Job soma o consumo
    do dia para o modelo no ledger `llm_daily_usage` e **para gracioso (exit 0)** ao
    atingir `BACKFILL_QUOTA_FRACTION` (0.8) da cota diaria, deixando >=20% para o
    worker ao vivo. Como NER e canon usam o mesmo modelo (Sonnet 4.6), ambos medem
    contra o **mesmo pool** de cota.

    **Args (guard secundario):** `--limit` (teto por execucao) e `--order asc`
    (acervo mais antigo primeiro).

    Config via Airflow Variables (Secret Manager backend): `ner_job_name`,
    `cloud_run_jobs_region`, `ner_run_limit`.
    """,
)
def ner_backfill():
    import os

    project_id = os.environ["GCP_PROJECT_ID"]
    region = Variable.get("cloud_run_jobs_region", default_var=DEFAULT_REGION)
    job_name = Variable.get("ner_job_name", default_var=DEFAULT_JOB_NAME)
    run_limit = Variable.get("ner_run_limit", default_var=DEFAULT_RUN_LIMIT)
    order = Variable.get("ner_backfill_order", default_var=DEFAULT_ORDER)

    # Formato do overrides conforme RunJobRequest.Overrides (proto-plus, snake_case):
    # passado direto ao hook -> RunJobRequest(overrides=...). Sobrescreve os args do
    # unico container do Job; os demais campos (env, imagem) vem do Job no Terraform.
    # NOTA: clear_args e args sao mutuamente exclusivos na API v2 — usar apenas args.
    CloudRunExecuteJobOperator(
        task_id="run_ner_backfill",
        project_id=project_id,
        region=region,
        job_name=job_name,
        overrides={
            "container_overrides": [
                {
                    "args": ["--limit", run_limit, "--order", order],
                }
            ],
        },
    )


dag_instance = ner_backfill()
