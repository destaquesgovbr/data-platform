"""DAG: backfills de enriquecimento (tema + resumo + sentimento) via Cloud Run Job.

Dispara o Cloud Run Job `destaquesgovbr-ner-backfill` (o mesmo do ner_backfill; imagem
e logica no repo data-science) pedindo, por container override, o script
`reenrich_combined_window.py` em vez do backfill de NER:

  - env BACKFILL_SCRIPT=reenrich_combined_window.py (o entrypoint do Job escolhe o
    script por essa env; sem ela roda backfill_ner_corpus.py, como no ner_backfill);
  - env ENRICHMENT_MODEL_ID, BEDROCK_DAILY_TOKEN_QUOTA (JSON {modelo: tokens/dia}) e
    BACKFILL_QUOTA_FRACTION (governador de cota, ledger `llm_daily_usage`);
  - args --select [--theme-code] --date-from [--date-to] --limit --workers [--dry-run]
    (contrato de 22/10 com o DS-1, data-science#49: exatamente essas flags).

O script e idempotente e resumivel: a selecao exclui o que ja foi feito, para gracioso
(exit 0) quando o consumo do dia do modelo bate fracao x cota e termina rapido com
"nada pendente" quando a selecao esta vazia.

Campanha atual (defaults dos params): B5, os artigos com summary '[MOCK]...' publicados
entre 2025-09-01 e 2026-03-01 (BRT), com o Haiku 4.5. Antes rodava numa maquina local,
que parou duas vezes (13/10 e 18/10).

Schedule: 22:30, 01:30 e 04:30 (Composer em America/Sao_Paulo, sem horario de verao;
= 01:30Z, 04:30Z e 07:30Z):
  - o ledger vira o dia a 00:00Z (CURRENT_DATE do Postgres em UTC = 21:00 BRT), entao
    o primeiro run pega a cota do dia inteira;
  - fora do pico do worker ao vivo (07h-21h BRT, quando chegam ~97% das noticias), que
    usa o mesmo modelo: o backfill nao disputa throughput do Bedrock com ele;
  - nao coincide com o canonicalize_backfill (00/06/12/18 BRT = 03/09/15/21Z) nem
    com o ner_backfill (02/08/14/20 BRT = 05/11/17/23Z), que usam o mesmo Job/banco.
Com limit=400 e workers=2 cada run leva ~15-20 min; dois runs gastam ~0,8 da cota
(~800 artigos/dia) e o terceiro pega a sobra ou repete um run que falhou.

Mudar a campanha:
  - permanente (schedule): PR alterando DEFAULT_PARAMS;
  - pontual: "Trigger DAG" com params (select, date_from, date_to, limit, workers,
    model_id, daily_token_quota, quota_fraction, dry_run, theme_code). dry_run=true so
    seleciona.

Tema 26 (D1, depois da migracao 034 e do deploy do DS-1, data-science#49): trigger com
select=theme26-candidates, date_from=2018-01-01 e date_to VAZIO (sem teto). Flags do
contrato: --select theme26-candidates (ou --select theme-code --theme-code <c>),
--date-from, [--date-to], --limit, --workers, [--dry-run]. O DS-1 grava so o tema e
audita na campanha tema26-llm-d1 (source llm:<model_id>), com os termos no titulo e no
conteudo e a guarda dos extras (fora do L1 19, so muda se o novo L1 for 26); nada disso
e param do DAG. O date_to herdado do B5 (2026-03-01) e recusado nas selecoes de tema:
cortaria ~70% do L1 19. select=theme-code + theme_code=19 pega so o L1 19.

Desligar: pausar o DAG na UI do Airflow (o estado de pausa persiste entre deploys) ou
remover este arquivo por PR. Quando a campanha termina os runs viram no-op
("nada pendente"), entao pausar e so economia de execucoes do Job.
"""

import datetime as dt
import json
import logging
import re
from collections.abc import Mapping
from typing import Any

try:
    from airflow.decorators import dag, task
    from airflow.models import Variable
    from airflow.providers.google.cloud.operators.cloud_run import (
        CloudRunExecuteJobOperator,
    )
    from airflow.sdk import Param
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Mesmo Job/regiao do ner_backfill (contrato fixo da infra, ner-backfill-job.tf). Em
# prod os valores vem das mesmas Airflow Variables (Secret Manager backend, prefixo
# airflow-variables-): ner_job_name, cloud_run_jobs_region. GCP_PROJECT_ID e env var
# do Composer (composer.tf).
DEFAULT_JOB_NAME = "destaquesgovbr-ner-backfill"
DEFAULT_REGION = "southamerica-east1"

# Contrato com o entrypoint do Job (repo data-science, docker/ner-backfill-job).
BACKFILL_SCRIPT = "reenrich_combined_window.py"

# Modos do reenrich_combined_window.py. null-theme e null-summary exigem --date-to
# (no maximo hoje BRT, checado pelo script): sem teto pegariam artigos do worker ao vivo.
# Tema 26 (D1, DS-1), so gravam o tema (auditoria em news_theme_changes, campanha
# tema26-llm-d1 do contrato de 22/10):
#   - theme-code: artigos com tema no codigo --theme-code (L1, L2 ou L3);
#   - theme26-candidates: L1 19, mais os de 04/05.02.01/15.02.03 do MDR ou que citam
#     termos de defesa civil no titulo e no conteudo.
# Os dois so pegam artigo ja com tema (nao disputam com o worker ao vivo): date_to opcional.
SELECT_CHOICES = ("mock", "null-theme", "null-summary", "theme-code", "theme26-candidates")
SELECTS_REQUIRING_DATE_TO = ("null-theme", "null-summary")
SELECT_WITH_THEME_CODE = "theme-code"
SELECT_THEME26_CANDIDATES = "theme26-candidates"
THEME_SELECTS = (SELECT_WITH_THEME_CODE, SELECT_THEME26_CANDIDATES)
THEME_CODE_PATTERN = r"^\d{2}(\.\d{2}){0,2}$"
# Params que o contrato de 22/10 nao tem (campanha, campos dos termos e codigos extras sao
# do DS-1). Vindos no conf do trigger, seriam ignorados calados: falham.
PARAMS_OUTSIDE_CONTRACT = ("campaign", "term_fields", "extra_codes")

HAIKU_45 = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Campanha B5 (summary '[MOCK]...'). Cota real do modelo; a fracao e aplicada pelo
# script uma unica vez (deixa o resto do dia para o worker ao vivo, mesmo modelo).
DEFAULT_PARAMS: dict[str, Any] = {
    "select": "mock",
    "date_from": "2025-09-01",
    "date_to": "2026-03-01",
    "limit": 400,
    "workers": 2,
    "model_id": HAIKU_45,
    "daily_token_quota": {HAIKU_45: 20000000},
    "quota_fraction": 0.8,
    "dry_run": False,
    "theme_code": None,
}


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} deve ser inteiro >= 1, recebido {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        raise ValueError(f"{name} deve ser inteiro >= 1, recebido {value!r}")
    if number < 1:
        raise ValueError(f"{name} deve ser inteiro >= 1, recebido {value!r}")
    return number


def _iso_date(name: str, value: Any) -> str:
    try:
        return dt.date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as e:
        raise ValueError(f"{name} invalida {value!r} (use AAAA-MM-DD)") from e


def _quota(value: Any, model_id: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"daily_token_quota nao e JSON valido: {e}") from e
    if not isinstance(value, Mapping):
        raise ValueError(f"daily_token_quota deve ser um objeto {{modelo: tokens}}: {value!r}")
    if model_id not in value:
        raise ValueError(
            f"daily_token_quota sem a chave do model_id {model_id!r}: o governador de cota "
            "rodaria sem-teto"
        )
    tokens = value[model_id]
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise ValueError(f"daily_token_quota[{model_id!r}] deve ser inteiro > 0: {tokens!r}")
    return dict(value)


def _fraction(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"quota_fraction deve estar em (0, 1], recebido {value!r}")
    try:
        fraction = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"quota_fraction deve estar em (0, 1], recebido {value!r}") from e
    if not 0 < fraction <= 1:
        raise ValueError(f"quota_fraction deve estar em (0, 1], recebido {value!r}")
    return fraction


def _theme_code(select: str, value: Any) -> str | None:
    code = value.strip() if isinstance(value, str) else value
    if select != SELECT_WITH_THEME_CODE:
        if code not in (None, ""):
            raise ValueError(f"theme_code so vale com select={SELECT_WITH_THEME_CODE}: {value!r}")
        return None
    if code in (None, ""):
        raise ValueError(f"select {SELECT_WITH_THEME_CODE} exige theme_code (ex.: 19, 05.02.01)")
    if not isinstance(code, str) or not re.match(THEME_CODE_PATTERN, code):
        raise ValueError(f"theme_code invalido {value!r} (use NN, NN.NN ou NN.NN.NN)")
    return code


def _reject_outside_contract(params: Mapping[str, Any]) -> None:
    outside = [name for name in PARAMS_OUTSIDE_CONTRACT if params.get(name) not in (None, "")]
    if outside:
        raise ValueError(
            f"params fora do contrato de 22/10: {', '.join(outside)}. O DS-1 grava na "
            "campanha tema26-llm-d1, busca os termos no titulo e no conteudo e aplica a "
            "guarda dos extras; o DAG so passa --select, --theme-code, --date-from, "
            "--date-to, --limit, --workers e --dry-run"
        )


def build_overrides(params: Mapping[str, Any]) -> dict:
    """Valida os params do run e monta o RunJobRequest.Overrides do Job.

    Formato conforme RunJobRequest.Overrides (proto-plus, snake_case), passado direto
    ao hook. "env" e mesclado ao env do Job (DATABASE_URL e a URI do Bedrock continuam
    vindo dos secrets); "args" substitui os args do container. clear_args e args sao
    mutuamente exclusivos na API v2, entao so args.

    Falha (ValueError) antes de subir o Job se a config estiver errada, em especial se
    a cota nao tiver a chave do modelo: o governador rodaria sem teto.
    """
    select = params.get("select")
    if select not in SELECT_CHOICES:
        raise ValueError(f"select deve ser um de {SELECT_CHOICES}, recebido {select!r}")
    _reject_outside_contract(params)
    theme_code = _theme_code(select, params.get("theme_code"))

    date_from = _iso_date("date_from", params.get("date_from"))
    raw_date_to = params.get("date_to")
    date_to = None if raw_date_to in (None, "") else _iso_date("date_to", raw_date_to)
    if date_to is not None and date_to <= date_from:
        raise ValueError(f"date_to (exclusivo) {date_to} deve ser posterior a {date_from}")
    if date_to is None and select in SELECTS_REQUIRING_DATE_TO:
        raise ValueError(f"select {select} exige date_to (exclusivo, no maximo hoje BRT)")
    if select in THEME_SELECTS and date_to == DEFAULT_PARAMS["date_to"]:
        # O trigger herda o default do B5: sem limpar o campo, a selecao de tema perderia
        # tudo de date_to em diante (341 dos 484 artigos do L1 19 em 22/10).
        raise ValueError(
            f"select {select} com date_to={date_to}, o default da campanha B5: cortaria os "
            "artigos dessa data em diante. Deixe date_to vazio (sem teto) ou informe outra "
            "data; no tema 26, date_from=2018-01-01"
        )

    limit = _positive_int("limit", params.get("limit"))
    workers = _positive_int("workers", params.get("workers"))

    model_id = str(params.get("model_id") or "").strip()
    if not model_id:
        raise ValueError("model_id e obrigatorio (vira ENRICHMENT_MODEL_ID)")
    quota = _quota(params.get("daily_token_quota"), model_id)
    fraction = _fraction(params.get("quota_fraction"))

    args = ["--select", select]
    if theme_code is not None:
        args += ["--theme-code", theme_code]
    args += ["--date-from", date_from]
    if date_to is not None:
        args += ["--date-to", date_to]
    args += ["--limit", str(limit), "--workers", str(workers)]
    if params.get("dry_run") is True or str(params.get("dry_run")).lower() == "true":
        args.append("--dry-run")

    env = [
        {"name": "BACKFILL_SCRIPT", "value": BACKFILL_SCRIPT},
        {"name": "ENRICHMENT_MODEL_ID", "value": model_id},
        {"name": "BEDROCK_DAILY_TOKEN_QUOTA", "value": json.dumps(quota)},
        {"name": "BACKFILL_QUOTA_FRACTION", "value": str(fraction)},
    ]
    return {"container_overrides": [{"args": args, "env": env}]}


@dag(
    dag_id="enrichment_backfill",
    description="Backfills de enriquecimento (B5/MOCK) via Cloud Run Job, sob governador de cota",
    schedule="30 1,4,22 * * *",  # 22:30, 01:30, 04:30 BRT = 01:30Z, 04:30Z, 07:30Z
    start_date=dt.datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    tags=["silver", "enrichment", "backfill"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": dt.timedelta(minutes=10),
        # Job com timeout de 7200s (ner-backfill-job.tf) + margem de partida.
        "execution_timeout": dt.timedelta(minutes=130),
    },
    params={
        "select": Param(
            DEFAULT_PARAMS["select"],
            type="string",
            enum=list(SELECT_CHOICES),
            description="Selecao do reenrich_combined_window.py",
        ),
        "date_from": Param(
            DEFAULT_PARAMS["date_from"],
            type="string",
            format="date",
            description="Dia BRT inicial (inclusivo)",
        ),
        "date_to": Param(
            DEFAULT_PARAMS["date_to"],
            type=["null", "string"],
            description="Dia BRT final (EXCLUSIVO); vazio so com select=mock",
        ),
        "limit": Param(
            DEFAULT_PARAMS["limit"],
            type="integer",
            minimum=1,
            maximum=5000,
            description="Teto de artigos por run (o governador de cota e o teto real)",
        ),
        "workers": Param(
            DEFAULT_PARAMS["workers"],
            type="integer",
            minimum=1,
            maximum=8,
            description="Chamadas Bedrock concorrentes",
        ),
        "model_id": Param(
            DEFAULT_PARAMS["model_id"],
            type="string",
            minLength=1,
            description="ENRICHMENT_MODEL_ID",
        ),
        "daily_token_quota": Param(
            DEFAULT_PARAMS["daily_token_quota"],
            type="object",
            description="BEDROCK_DAILY_TOKEN_QUOTA: {modelo: tokens/dia}; precisa da chave do model_id",
        ),
        "quota_fraction": Param(
            DEFAULT_PARAMS["quota_fraction"],
            type="number",
            exclusiveMinimum=0,
            maximum=1,
            description="BACKFILL_QUOTA_FRACTION (o resto do dia fica para o worker ao vivo)",
        ),
        "dry_run": Param(
            DEFAULT_PARAMS["dry_run"],
            type="boolean",
            description="So seleciona e lista; nao chama o Bedrock nem escreve",
        ),
        "theme_code": Param(
            DEFAULT_PARAMS["theme_code"],
            type=["null", "string"],
            pattern=THEME_CODE_PATTERN,
            description="Codigo de tema (NN, NN.NN ou NN.NN.NN); so com select=theme-code",
        ),
    },
    doc_md="""
    ### Backfills de enriquecimento (tema + resumo + sentimento)

    Dispara o Cloud Run Job **destaquesgovbr-ner-backfill** com
    `BACKFILL_SCRIPT=reenrich_combined_window.py` (repo data-science). O script NUNCA
    roda o NER nem publica `dgb.news.enriched`; e idempotente e resumivel.

    **Campanha atual (defaults):** B5, os `[MOCK]` de 2025-09-01 a 2026-03-01 com o
    Haiku 4.5, cota 20M tokens/dia x fracao 0.8. Selecao vazia -> "nada pendente".

    **Schedule:** 22:30, 01:30 e 04:30 BRT (01:30Z, 04:30Z, 07:30Z): depois da virada
    do ledger (00:00Z), fora do pico do worker ao vivo e fora dos horarios do canon e
    do ner_backfill.

    **Trigger manual com params:** `select`, `date_from`, `date_to`, `limit`,
    `workers`, `model_id`, `daily_token_quota`, `quota_fraction`, `dry_run`,
    `theme_code`. A task
    `build_overrides` valida tudo antes de subir o Job (cota sem a chave do modelo
    falha: o governador rodaria sem teto).

    **Mudar a campanha de forma permanente:** PR em `DEFAULT_PARAMS`.
    **Desligar:** pausar o DAG na UI.

    **Tema 26 (D1):** `select=theme26-candidates` (L1 19, mais 04/05.02.01/15.02.03 do
    MDR ou com termo de defesa civil), `date_from=2018-01-01` e **`date_to` vazio** (o
    default do B5, 2026-03-01, e recusado nas selecoes de tema). Flags do contrato de
    22/10: `--select`, `--theme-code` (so no `theme-code`), `--date-from`, `--date-to`,
    `--limit`, `--workers` e `--dry-run`. O DS-1 grava so o tema na campanha
    `tema26-llm-d1` de `news_theme_changes`, com os termos no titulo e no conteudo e a
    guarda dos extras. `select=theme-code` + `theme_code` (ex.: `19`) pega so a
    subarvore do codigo.
    Sempre `dry_run=true`, depois `limit=10`, depois o lote completo.

    **Atencao:** run verde nao significa zero falhas por artigo. Ver a linha `FIM:` no
    log da execucao do Job; artigos com falha sao selecionados de novo no proximo run.
    """,
)
def enrichment_backfill():
    import os

    project_id = os.environ["GCP_PROJECT_ID"]
    region = Variable.get("cloud_run_jobs_region", default_var=DEFAULT_REGION)
    job_name = Variable.get("ner_job_name", default_var=DEFAULT_JOB_NAME)

    @task(task_id="build_overrides")
    def build_overrides_task(params: Mapping[str, Any] | None = None) -> dict:
        overrides = build_overrides(params or {})
        (container,) = overrides["container_overrides"]
        logger.info("args=%s env=%s", container["args"], container["env"])
        return overrides

    # overrides e campo templated do operador: o XComArg da task acima e resolvido
    # na renderizacao e ja cria a dependencia build_overrides >> run_enrichment_backfill.
    CloudRunExecuteJobOperator(
        task_id="run_enrichment_backfill",
        project_id=project_id,
        region=region,
        job_name=job_name,
        overrides=build_overrides_task(),
    )


dag_instance = enrichment_backfill()
