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

- **Airflow**: 3.0.1 (Cloud Composer)
- **Composer**: `destaquesgovbr-composer` (us-central1)
- **GCP Project**: `inspire-7-finep`
- **Python**: 3.11

### Pipeline de Dados

```
Scrapers (Cloud Run, a cada 15 min)
    |
PostgreSQL (Cloud SQL, private IP)
    |
Enriquecimento IA (Cogfy) — temas + summaries
    |
Embeddings API (Cloud Run) — 768-dim vectors (pgvector)
    |
Typesense (busca textual + semantica)
    |
HuggingFace (dados abertos — sync diario)
    |
Portal Web (Next.js)
```

### Airflow Connections Disponiveis

| Connection ID | Tipo | Descricao |
|---|---|---|
| `postgres_default` | PostgreSQL | Cloud SQL (private IP via VPC peering) |
| `huggingface_default` | HTTP | Token HF no campo `password` |
| `embeddings_api` | HTTP | Cloud Run endpoint no `host`, API key no `password` |
| `federation_postgres` | PostgreSQL | BD ActivityPub (mesmo Cloud SQL) |

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

| Repo | DAG | Schedule | Descricao |
|---|---|---|---|
| `scraper` | `scrape_{agency}` (~158 DAGs) | `*/15 * * * *` | Scraping dinamico |
| `data-publishing` | `sync_postgres_to_huggingface` | `0 6 * * *` | PG → HuggingFace |
| `embeddings` | `generate_embeddings` | `0 5 * * *` | Gera embeddings via API |

### Padrao de Deploy

```
{repo}/
├── src/{modulo_plugin}/     → plugins Composer (PYTHONPATH)
│   ├── __init__.py          → relative imports
│   └── ...                  → logica de negocio
├── dags/
│   ├── minha_dag.py         → DAG (importa do plugin)
│   └── requirements.txt     → deps pip para Composer
└── .github/workflows/
    └── composer-deploy-dags.yaml  → chama reusable workflow
```

O reusable workflow `destaquesgovbr/reusable-workflows/.github/workflows/composer-deploy-dags.yml@v1` faz:
1. Valida syntax Python e imports
2. Autentica via Workload Identity (OIDC)
3. Sync DAGs para `{bucket}/dags/{subdir}/`
4. Sync plugins para `{bucket}/plugins/{basename(plugins_local_path)}/`
5. Espera Airflow parsear

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
- Usar relative imports (`.core`, `.utils`) — o nome do folder pode mudar no Composer
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
    schedule="0 5 * * *",  # Ajustar conforme necessidade
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
- Sempre tratar `logical_date is None` para execucao manual
- Usar `@dag` + `@task` decorators (Airflow 3 TaskFlow API)
- `catchup=False` sempre (a menos que haja motivo especifico)
- Instanciar a DAG no final: `dag_instance = {dag_id}_dag()`

### 2.3 Requirements

Crie `dags/requirements.txt` com as dependencias pip que o Composer precisa instalar:

```
# Apenas deps nao incluidas no Composer por padrao
httpx>=0.27.0
```

Nao incluir: `apache-airflow`, `psycopg2` (ja incluidos no Composer).

### 2.4 Deploy Workflow

Crie `.github/workflows/composer-deploy-dags.yaml`:

```yaml
name: Deploy {Nome} DAGs to Composer

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
    uses: destaquesgovbr/reusable-workflows/.github/workflows/composer-deploy-dags.yml@v1
    with:
      dags_local_path: dags
      dags_bucket_subdir: {repo_name}
      plugins_local_path: src/{nome_modulo}
      check_imports: true
      rsync_exclude: 'requirements\.txt$'
```

**Notas**:
- `dags_bucket_subdir` define o subfolder em `{bucket}/dags/` (usar nome do repo)
- `plugins_local_path` define a fonte; o destino sera `{bucket}/plugins/{basename}/`
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

Se a DAG precisa de uma connection que ainda nao existe, criar via Secret Manager:

```bash
# Formato URI para Airflow (prefix airflow-connections-)
echo "http://:API_KEY@hostname" | \
  gcloud secrets create airflow-connections-{connection_id} \
    --data-file=- \
    --replication-policy=automatic \
    --project=inspire-7-finep

# Conceder acesso ao Composer SA
gcloud secrets add-iam-policy-binding airflow-connections-{connection_id} \
  --member="serviceAccount:destaquesgovbr-composer@inspire-7-finep.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=inspire-7-finep
```

Connections HTTP no Airflow: o `host` e o hostname (sem `https://`), `password` e a API key. Na DAG, reconstruir a URL:
```python
conn = BaseHook.get_connection('minha_connection')
url = f"https://{conn.host}"
api_key = conn.password
```

### 3.3 Airflow Variable (se necessaria)

```bash
echo "valor" | \
  gcloud secrets create airflow-variables-{variable_name} \
    --data-file=- \
    --replication-policy=automatic \
    --project=inspire-7-finep

gcloud secrets add-iam-policy-binding airflow-variables-{variable_name} \
  --member="serviceAccount:destaquesgovbr-composer@inspire-7-finep.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=inspire-7-finep
```

---

## Passo 4: Deploy e Validacao

### 4.1 Commit e Push

```bash
git add dags/ src/{nome_modulo}/ .github/workflows/composer-deploy-dags.yaml tests/
git commit -m "feat: add {dag_id} DAG and {nome_modulo} plugin"
git push -u origin {branch}
```

### 4.2 Criar PR e Merge

```bash
gh pr create --title "feat: add {dag_id} DAG" --body "..."
gh pr merge --merge --admin
```

### 4.3 Trigger Deploy

```bash
gh workflow run composer-deploy-dags.yaml
gh run list --workflow=composer-deploy-dags.yaml --limit 1
gh run watch {run_id}
```

### 4.4 Verificar DAG no Airflow

```bash
AIRFLOW_URI=$(gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 --format="value(config.airflowUri)")

curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "$AIRFLOW_URI/api/v2/dags/{dag_id}" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'DAG: {d[\"dag_id\"]}, paused: {d[\"is_paused\"]}, schedule: {d.get(\"timetable_summary\",\"?\")}')
"
```

Se a DAG nao aparecer, verificar import errors:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "$AIRFLOW_URI/api/v2/importErrors" | python3 -c "
import sys,json
data=json.load(sys.stdin)
for e in data.get('import_errors',[]):
    print(f'{e[\"filename\"]}: {e[\"stack_trace\"][:300]}')
"
```

### 4.5 Trigger Manual

```bash
LOGICAL_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "$AIRFLOW_URI/api/v2/dags/{dag_id}/dagRuns" \
  -d "{\"logical_date\": \"$LOGICAL_DATE\"}"
```

### 4.6 Monitorar Execucao

```bash
DAG_RUN_ID="manual__..."
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "$AIRFLOW_URI/api/v2/dags/{dag_id}/dagRuns/$DAG_RUN_ID" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['state'])"
```

---

## Checklist Final

- [ ] Plugin em `src/{nome_modulo}/` com relative imports
- [ ] DAG em `dags/{dag_id}.py` com imports dentro da `@task`
- [ ] `dags/requirements.txt` com deps extras
- [ ] `.github/workflows/composer-deploy-dags.yaml` configurado
- [ ] Testes unitarios para o plugin
- [ ] WIF configurado (se repo novo)
- [ ] Airflow connection criada (se necessaria)
- [ ] Deploy workflow executou com sucesso
- [ ] DAG visivel no Airflow UI
- [ ] Trigger manual executou com sucesso
