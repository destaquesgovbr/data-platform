---
name: criar-dag
description: Cria uma nova DAG Airflow no padrao DGB. Gera o modulo plugin, a DAG, o workflow de deploy e configura a infra necessaria. Use quando o usuario pedir para criar DAG, criar pipeline Airflow, adicionar DAG, ou criar um job agendado.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion
argument-hint: [descricao do pipeline em linguagem natural]
---

# Criar DAG Airflow — DestaquesGovBr

Crie uma nova DAG seguindo o padrao estabelecido do projeto DGB.

---

## Arquitetura de Referencia DGB

### Ambiente

- **Airflow**: 3.1.8 proprio, na VM `destaquesgovbr-airflow` (docker compose, `LocalExecutor`, `southamerica-east1-a`). O Cloud Composer foi desligado em 11/2026 (Fase 7 de `infra/_plan/migrar-composer-para-airflow-proprio.md`)
- **UI e REST API**: https://airflow.dgb.app.gov.br (atras do IAP)
- **Bucket**: `gs://destaquesgovbr-airflow` (`dags/<repo>/` e `plugins/<pacote>/`), espelhado na VM pelo container `dag-sync` a cada 60 s
- **Fuso dos crons**: `America/Sao_Paulo` (`core.default_timezone`); `run_id` e `logical_date` aparecem em UTC
- **GCP Project**: `inspire-7-finep`
- **Python**: 3.11 (o da imagem do Airflow, `infra/airflow/Dockerfile`)
- **Operacao** (SSH, CLI, logs, catch-up ao despausar): `docs/runbooks/airflow-vm.md`

### Pipeline de Dados

```
Scraping (DAGs scrape_agencies, a cada 2 h das 06 as 22 h BRT, e scrape_ebc)
    ↓ Pub/Sub: dgb.news.scraped
Bronze Writer → GCS (raw JSON)
    ↓
PostgreSQL (Cloud SQL, private IP) ← Silver layer
    ↓ Pub/Sub: dgb.news.enriched
Feature Worker → news_features
Thumbnail Worker → GCS (thumbnails)
Typesense Sync → Typesense (busca)
    ↓
Airflow DAGs → BigQuery (Gold layer)
    ↓
Portal Web (Next.js)
```

### Airflow Connections Disponiveis

| Connection ID | Tipo | Descricao |
|---|---|---|
| `postgres_default` | PostgreSQL | Cloud SQL (private IP via VPC peering) |
| `umami_postgres` | PostgreSQL | BD do Umami (mesmo Cloud SQL) |
| `huggingface_default` | HTTP | Token HF no campo `password` |
| `embeddings_api` | HTTP | Cloud Run endpoint no `host`, API key no `password` |
| `aws_bedrock` | AWS | Credenciais do Bedrock (enriquecimento por LLM) |

Todas vem do Secret Manager (secrets `airflow-connections-*`), pelo secrets backend da VM.

**Uso**:
```python
from airflow.hooks.base import BaseHook
conn = BaseHook.get_connection('postgres_default')
database_url = conn.get_uri()
```

Para PostgreSQL via Hook:
```python
from airflow.providers.postgres.hooks.postgres import PostgresHook
pg_hook = PostgresHook(postgres_conn_id="postgres_default")
records = pg_hook.get_records(SQL_QUERY, parameters=[param1])
```

### Airflow Variables Disponiveis

| Variable | Descricao |
|---|---|
| `typesense_host` | IP externo do Typesense |
| `scraper_api_url` | URL da API do scraper (Cloud Run) |
| `gcp_project_id` | `inspire-7-finep` |
| `gcp_region` | `southamerica-east1` |
| `postgres_db` | Nome do banco PostgreSQL |

Lista completa: secrets `airflow-variables-*` no Secret Manager
(`gcloud secrets list --filter='name~airflow-variables-' --project=inspire-7-finep`).

### Schema PostgreSQL (tabelas principais)

**`news`** (~300k registros):
- `id` (PK), `unique_id`, `agency_key`, `agency_name`
- `published_at`, `updated_datetime`, `extracted_at`
- `title`, `subtitle`, `editorial_lead`, `url`, `content`
- `image_url`, `video_url`, `category`, `tags`
- `summary` (gerado por IA via Cogfy)
- `theme_l1_id`, `theme_l2_id`, `theme_l3_id`, `most_specific_theme_id` (FKs)
- `content_embedding` (pgvector, 768-dim)
- `embedding_generated_at`

**`agencies`** (158 registros):
- `id`, `key`, `name`, `abbreviation`, `url`

**`themes`** (taxonomia hierarquica, 3 niveis):
- `id`, `parent_id`, `code`, `label`, `level`

### Repos com DAGs Existentes

| Repo | Subpasta no bucket | DAGs |
|---|---|---|
| `scraper` | `dags/scraper/` | `scrape_agencies` (task mapeada por agencia, `0 6-22/2 * * *`), `scrape_ebc`, `monitor_scraping_health`, `cleanup_old_scrape_runs`, `scraper_coverage_report` |
| `data-platform` | `dags/data-platform/` | 12 DAGs (sync BigQuery, trending, clusters, grafo de entidades, thumbnails, integridade, backfills de NER/canonicalizacao/enriquecimento); schedules em `docs/dags/README.md` |
| `clipping` | `dags/clipping/` | `dispatch_clippings` |
| `data-publishing` | `dags/data-publishing/` | `sync_postgres_to_huggingface` |
| `infra` | `dags/platform/` (reservada) | `airflow_heartbeat` |

Convencao completa: `docs/architecture/decentralized-dags.md`.

### Padrao de Deploy

```
{repo}/
├── src/{modulo_plugin}/     → plugins (gs://destaquesgovbr-airflow/plugins/{modulo_plugin}/, no sys.path das tasks)
│   ├── __init__.py          → relative imports
│   └── ...                  → logica de negocio
├── dags/
│   ├── minha_dag.py         → DAG (importa do plugin)
│   └── requirements.txt     → so documentacao: nao e instalado (ver 2.3)
└── .github/workflows/
    └── deploy-dags.yaml     → chama o reusable workflow
```

O reusable workflow `destaquesgovbr/reusable-workflows/.github/workflows/airflow-deploy-dags.yml@v3` faz:
1. Confere os inputs (subpasta obrigatoria, sem `/`, nunca `platform`)
2. Valida as DAGs com o Airflow 3.1.8 da imagem (`py_compile` recursivo; imports com `check_imports: true`, sem bloquear)
3. Autentica via Workload Identity (OIDC)
4. Sync dos plugins para `gs://destaquesgovbr-airflow/plugins/{basename(plugins_local_path)}/` e das DAGs para `gs://destaquesgovbr-airflow/dags/{dags_bucket_subdir}/` (o rsync apaga no destino o que saiu do repo)
5. Espera 60 s. Nao confere se a DAG apareceu no Airflow (ver 4.4)

O `composer-deploy-dags.yml@v1` esta descontinuado: o Composer foi desligado e ele falha no
`gcloud composer environments describe`.

---

## Passo 1: Analisar a necessidade

Analise `$ARGUMENTS` e identifique:

1. **O que a DAG faz**: qual transformacao/sync/processamento
2. **Dados de entrada**: de onde le (PostgreSQL, API, arquivo)
3. **Dados de saida**: para onde grava (PostgreSQL, API, storage)
4. **Connections necessarias**: quais connections Airflow precisa (ver lista acima)
5. **Schedule**: frequencia de execucao (cron)
6. **Repo destino**: onde a DAG deve morar

Use AskUserQuestion para confirmar/ajustar:

- **Repo**: Repo existente (data-platform, data-publishing, embeddings, scraper) ou criar novo?
- **Nome da DAG**: `dag_id` proposto
- **Schedule**: cron expression
- **Connections**: novas connections necessarias?

Se o repo for novo, anotar que sera necessario:
- Criar repo no GitHub
- Adicionar WIF no terraform (infra)

---

## Passo 2: Criar a estrutura

### 2.1 Plugin (logica de negocio)

Crie o modulo em `src/{nome_modulo}/` com relative imports:

```python
# src/{nome_modulo}/__init__.py
from .core import MinhaClasse

__all__ = ["MinhaClasse"]
```

```python
# src/{nome_modulo}/core.py
"""Logica de negocio do pipeline."""

import logging

logger = logging.getLogger(__name__)


class MinhaClasse:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def processar(self, start_date: str, end_date: str) -> dict:
        """Executa o processamento."""
        # Implementar logica
        return {"processed": 0, "successful": 0, "failed": 0}
```

**Regras**:
- Usar relative imports (`.core`, `.utils`) dentro do pacote: ele e publicado em `plugins/{basename}/` e as DAGs o importam por esse nome
- Nao depender de variaves de ambiente — receber tudo via parametros
- Retornar dict com estatisticas para o log do Airflow
- Usar `logging` padrao (Airflow captura automaticamente)

### 2.2 DAG

Crie em `dags/{dag_id}.py`:

```python
"""
DAG para [descricao curta].

[Descricao mais longa do pipeline.]
"""

from datetime import datetime, timedelta, timezone
import logging

from airflow.decorators import dag, task
from airflow.hooks.base import BaseHook


@dag(
    dag_id="{dag_id}",
    description="[Descricao curta]",
    schedule="0 5 * * *",  # Ajustar conforme necessidade (horario de Brasilia)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["{area}", "postgres", "daily"],
    default_args={
        "owner": "{repo_name}",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
    },
)
def {dag_id}_dag():
    """[Docstring da DAG.]"""

    @task
    def processar(logical_date=None) -> dict:
        """[Docstring da task.]"""
        from {nome_modulo} import MinhaClasse

        # Obter connections
        pg_conn = BaseHook.get_connection("postgres_default")

        # Data alvo: dia anterior
        if logical_date is None:
            logical_date = datetime.now(timezone.utc)
            logging.info("Execucao manual — usando data atual como logical_date")
        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        logging.info(f"Processando data: {target_date}")

        # Executar
        obj = MinhaClasse(database_url=pg_conn.get_uri())
        result = obj.processar(start_date=target_date, end_date=target_date)

        # Log final
        logging.info("=" * 60)
        logging.info(f"Resultado: {result}")
        logging.info("=" * 60)

        return result

    processar()


dag_instance = {dag_id}_dag()
```

**Regras**:
- Imports pesados (`from {nome_modulo} import ...`) DENTRO da `@task`, nao no topo do arquivo — evita erro de parse se o plugin ainda nao esta deployado
- Sempre tratar `logical_date is None`: e o caso do trigger pela CLI sem `--logical-date` (pela UI e pela API o run manual tem a hora do disparo)
- Se a DAG grava com append (ex.: `WRITE_APPEND` no BigQuery), o run manual repete o periodo do run agendado: documente no `doc_md` que ela nao deve ser disparada a mao (como `sync_pg_to_bigquery`)
- Usar `@dag` + `@task` decorators (Airflow 3 TaskFlow API)
- `catchup=False` sempre (a menos que haja motivo especifico)
- Em task **mapeada** (`.expand()`), NAO use `retry_exponential_backoff`: no Airflow 3.1 o retry dela derruba o loop do scheduler. Use so `retry_delay` fixo
- Instanciar a DAG no final: `dag_instance = {dag_id}_dag()`

### 2.3 Dependencias Python

**IMPORTANTE**: o `dags/requirements.txt` NAO e instalado. As tasks rodam na imagem do Airflow
proprio (`infra/airflow/Dockerfile`; com `LocalExecutor`, dentro do container do scheduler).

Ja estao na imagem (lista em `infra/airflow/requirements.txt`): `apache-airflow` 3.1.8, providers
`google`, `postgres` e `standard`, `google-cloud-{bigquery,storage,run,logging}`, `google-auth`,
`pandas`, `numpy`, `pyarrow`, `psycopg2-binary`, `SQLAlchemy`, `httpx`, `requests`, `PyYAML`,
`huggingface_hub` e `typesense`.

Se precisar de pacote extra:
1. **Caso geral**: PR no repo `infra` adicionando o pacote em `airflow/requirements.txt` (sem versao
   vale a das constraints do Airflow; fora delas, fixar a versao). O workflow `airflow-image.yml`
   builda a imagem, e um segundo PR troca `airflow_image_tag` em `terraform/variables.tf`; o apply
   recria os containers da VM. Ver `infra/airflow/README.md`
2. **Pacote puro Python, pequeno e so desta DAG**: pode ir junto dos plugins, como o `pyphen` que o
   deploy do data-platform vendoriza em `plugins/pyphen/`
3. So mergear a DAG depois que o pacote estiver na VM; senao ela entra com import error

Manter `dags/requirements.txt` apenas como documentacao das deps necessarias (nao e usado no deploy).

### 2.4 Deploy Workflow

Se o repo ja publica DAGs, NAO crie outro workflow: confira se os `paths` do existente cobrem os
arquivos novos.

| Repo | Workflow |
|---|---|
| `data-platform` | `composer-deploy-dags.yaml` (nome historico). DAGs em `src/data_platform/dags/`; os plugins sao montados num job proprio, e um modulo novo de `src/data_platform/jobs/` precisa entrar no passo "Prepare plugins directory" |
| `scraper`, `data-publishing` | `composer-deploy-dags.yaml` (nome historico) |
| `clipping` | `deploy-dags.yaml` |

Repo novo: crie `.github/workflows/deploy-dags.yaml`:

```yaml
name: Deploy {Nome} DAGs to Airflow

on:
  push:
    branches: [main]
    paths:
      - 'dags/**'
      - 'src/{nome_modulo}/**'
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    uses: destaquesgovbr/reusable-workflows/.github/workflows/airflow-deploy-dags.yml@v3
    with:
      dags_local_path: dags
      dags_bucket_subdir: {repo_name}
      plugins_local_path: src/{nome_modulo}
      check_imports: true
      rsync_exclude: 'requirements\.txt$'
```

**Notas**:
- `dags_bucket_subdir` define a subpasta em `gs://destaquesgovbr-airflow/dags/` (usar o nome do repo; `platform` e reservada)
- `plugins_local_path` define a fonte; o destino sera `gs://destaquesgovbr-airflow/plugins/{basename}/`
- `buckets` fica no default (`destaquesgovbr-airflow`)
- `permissions.id-token: write` e obrigatorio para WIF/OIDC
- Se o repo NAO tem plugins (ex: scraper), omitir `plugins_local_path`

### 2.5 Testes

Criar testes unitarios para a logica de negocio do plugin (nao para a DAG em si):

```python
# tests/test_{nome_modulo}.py
from {nome_modulo}.core import MinhaClasse

class TestMinhaClasse:
    def test_processar_sem_registros(self):
        # ...
```

---

## Passo 3: Configurar Infra (se necessario)

### 3.1 WIF (Workload Identity Federation)

Se o repo e **novo** (nao existe no WIF), adicionar binding em `infra/terraform/workload-identity.tf`:

```hcl
resource "google_service_account_iam_member" "github_actions_workload_identity_{repo_name}" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_organization}/{repo_name}"
}
```

Criar PR no repo `infra`, aguardar merge e terraform apply.

### 3.2 Airflow Connection (se necessaria)

O secrets backend da VM le os secrets `airflow-connections-{connection_id}` do Secret Manager com a
SA da VM, `destaquesgovbr-composer@inspire-7-finep.iam.gserviceaccount.com` (o nome ficou do
Composer; no Terraform e `google_service_account.composer`). Secret e IAM sao Terraform: PR no repo
`infra`, em `terraform/composer_secrets.tf`, no mesmo padrao dos existentes. Nao crie secret nem
conceda IAM com `gcloud` direto.

```hcl
resource "google_secret_manager_secret" "airflow_{connection_id}_conn" {
  secret_id = "airflow-connections-{connection_id}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_iam_member" "composer_airflow_{connection_id}" {
  secret_id = google_secret_manager_secret.airflow_{connection_id}_conn.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.composer.email}"
}
```

O valor e a URI da connection (ex.: `http://:API_KEY@hostname`). Se ele vem de outro recurso do
Terraform, entra numa `google_secret_manager_secret_version` no mesmo PR. Se e uma credencial
externa, o Terraform cria so o secret e o usuario adiciona a versao depois (o arquivo tem exemplos
de `gcloud secrets versions add` nos comentarios).

Connections HTTP no Airflow: o `host` e o hostname (sem `https://`), `password` e a API key. Na DAG, reconstruir a URL:
```python
conn = BaseHook.get_connection('minha_connection')
url = f"https://{conn.host}"
api_key = conn.password
```

### 3.3 Airflow Variable (se necessaria)

Mesmo padrao da 3.2, com o secret `airflow-variables-{variable_name}` (PR no `infra`, em
`terraform/composer_secrets.tf`, com o `google_secret_manager_secret_iam_member` para
`google_service_account.composer`). Para variavel cujo valor sai de outro recurso (URL de Cloud
Run, nome de Job), a `google_secret_manager_secret_version` vai no mesmo PR.

---

## Passo 4: Deploy e Validacao

### 4.1 Commit e Push

```bash
git add dags/ src/{nome_modulo}/ .github/workflows/deploy-dags.yaml tests/
git commit -m "feat: add {dag_id} DAG and {nome_modulo} plugin"
git push -u origin {branch}
```

### 4.2 Criar PR e Merge

```bash
gh pr create --title "feat: add {dag_id} DAG" --body "..."
gh pr merge --merge --admin
```

### 4.3 Trigger Deploy

O push na main ja dispara o deploy. Para rodar de novo (use o nome do workflow do repo, ver 2.4):

```bash
gh workflow run deploy-dags.yaml
gh run list --workflow=deploy-dags.yaml --limit 1
gh run watch {run_id}
```

### 4.4 Verificar DAG no Airflow

Arquivo novo aparece em ate ~2 min depois do deploy (60 s do `dag-sync` + ate 60 s do refresh do
bundle). UI: https://airflow.dgb.app.gov.br (o IAP exige `roles/iap.httpsResourceAccessor`).

Pela CLI do Airflow, via SSH pelo IAP (so os admins do Airflow tem `roles/iap.tunnelResourceAccessor`):

```bash
gcloud compute ssh destaquesgovbr-airflow --zone=southamerica-east1-a \
  --tunnel-through-iap --project=inspire-7-finep \
  --command='cd /opt/airflow && sudo docker compose exec -T airflow-scheduler airflow dags list-import-errors && sudo docker compose exec -T airflow-scheduler airflow dags list | grep {dag_id}'
```

`dags list-import-errors` deve sair vazio. Se a DAG nao aparecer, seguir "DAG sumiu ou nao aparece"
em `docs/runbooks/airflow-vm.md` (do data-platform). A REST API (`/api/v2`) tambem passa pelo IAP e
pede dois tokens (ID token do IAP e o JWT do Airflow em `/auth/token`); para conferir uma DAG, a CLI
por SSH e mais simples.

### 4.5 Despausar e Trigger Manual

DAG nova nasce **pausada**, e run de DAG pausada fica `queued` sem rodar. Antes de despausar, ler
"Catch-up ao despausar" no runbook: com `catchup=False`, o despause roda **na hora** o horario mais
recente que ja passou.

Pela UI (toggle da DAG e botao Trigger) ou pela CLI, na VM:

```bash
cd /opt/airflow
sudo docker compose exec airflow-scheduler airflow dags unpause {dag_id}
sudo docker compose exec airflow-scheduler airflow dags trigger {dag_id}
```

Nao dispare manualmente DAG que grava com append (ver 2.2): o run manual repete o periodo do run
agendado.

### 4.6 Monitorar Execucao

Na UI (DAG → run → task → Logs) ou pela CLI, na VM:

```bash
sudo docker compose exec airflow-scheduler airflow dags list-runs {dag_id}
sudo docker compose exec airflow-scheduler airflow dags state {dag_id} '<run_id>'
```

Logs das tasks tambem ficam em `gs://destaquesgovbr-airflow/logs/dag_id={dag_id}/` (30 dias).

---

## Checklist Final

- [ ] Plugin em `src/{nome_modulo}/` com relative imports
- [ ] DAG em `dags/{dag_id}.py` com imports dentro da `@task`
- [ ] `dags/requirements.txt` com deps extras (so documentacao)
- [ ] Pacote extra na imagem (`infra/airflow/requirements.txt`) ou nos plugins (se necessario)
- [ ] Workflow de deploy com `airflow-deploy-dags.yml@v3` (ou o workflow existente do repo cobrindo os arquivos novos)
- [ ] Testes unitarios para o plugin
- [ ] WIF configurado (se repo novo)
- [ ] Secret e IAM da connection/variable por PR no `infra` (se necessario)
- [ ] Deploy workflow executou com sucesso
- [ ] DAG visivel no Airflow UI, sem import error
- [ ] DAG despausada (conferido o catch-up)
- [ ] Trigger manual executou com sucesso (se a DAG aguenta rodar de novo o mesmo periodo)
