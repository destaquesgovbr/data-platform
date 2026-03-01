# Plano: Criar repo `data-publishing` e migrar DAG sync_postgres_to_huggingface

## Contexto

O `data-platform` hoje é um repo monolítico que mistura responsabilidades: enriquecimento (Cogfy), embeddings, Typesense sync, e publicação HuggingFace. A DAG `sync_postgres_to_huggingface.py` é a única DAG restante no repo e faz algo conceitualmente diferente — **publicação de dados** (PG → HuggingFace).

Vamos criar o repo `data-publishing` para isolar essa responsabilidade, seguindo o padrão da org (cada repo = um domínio claro).

## Estrutura do repo `data-publishing`

```
data-publishing/
├── src/data_publishing/
│   ├── __init__.py
│   └── hf/                          # Módulo HuggingFace (deploy como plugin)
│       ├── __init__.py
│       ├── schema.py                 # PyArrow schema + HF_COLUMNS + conversão
│       ├── dedup.py                  # Consulta IDs existentes via Dataset Viewer API
│       ├── uploader.py               # Upload parquet shard + cleanup metadata
│       └── readme_sanitizer.py       # Sanitiza README.md (remove stale splits)
├── dags/
│   ├── sync_postgres_to_huggingface.py  # DAG refatorada (importa de data_publishing.hf)
│   └── requirements.txt                 # Deps pip para Composer
├── tests/
│   └── unit/
│       └── test_dedup.py
├── .github/workflows/
│   └── composer-deploy-dags.yaml     # Deploy DAGs + plugins via reusable workflow
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

## Decisões de Design

### Plugins no Composer para código Python custom

O Composer adiciona `{bucket}/plugins/` ao `PYTHONPATH` dos workers. Vamos deployar `src/data_publishing/` para `{bucket}/plugins/data_publishing/`, permitindo que a DAG faça:

```python
from data_publishing.hf.schema import build_arrow_schema, records_to_arrow_table
from data_publishing.hf.dedup import get_existing_ids_for_date
from data_publishing.hf.uploader import upload_shard
```

Isso permite:
- DAG limpa (orquestração) com lógica em módulos testáveis
- Testes unitários locais dos módulos
- Reuso futuro (ex: publicar para outros destinos)

### Evolução do reusable workflow

O workflow `composer-deploy-dags.yml` precisa de um novo input opcional `plugins_local_path` para deployar plugins além de DAGs. Quando fornecido, o workflow faz `gsutil rsync` adicional para `{bucket}/plugins/{subdir}/`.

### DAGs path: `dags/` (raiz)

Seguindo o padrão do `scraper` — simples e evita paths longos.

### Airflow Connections (já existem no Composer)

- `postgres_default` — PostgreSQL (Cloud SQL)
- `huggingface_default` — HF token

## Parte 1: Evoluir o reusable workflow

**Repo**: `reusable-workflows`
**Arquivo**: `.github/workflows/composer-deploy-dags.yml`

### Novo input

| Input | Tipo | Required | Default | Descrição |
|-------|------|----------|---------|-----------|
| `plugins_local_path` | string | false | `""` | Path local dos plugins (ex: `src/data_publishing`). Se vazio, pula deploy de plugins. |

### Novos steps no job `deploy-dags`

Após o step "Deploy DAGs to GCS", adicionar:

```yaml
- name: Deploy plugins to GCS
  if: inputs.plugins_local_path != ''
  run: |
    PLUGINS_BUCKET=$(echo "${{ steps.composer.outputs.dags_bucket }}" | sed 's|/dags$|/plugins|')
    echo "Syncing plugins to $PLUGINS_BUCKET/${{ inputs.dags_bucket_subdir }}/..."
    gsutil -m rsync -r -d \
      ${{ inputs.plugins_local_path }}/ $PLUGINS_BUCKET/${{ inputs.dags_bucket_subdir }}/
    echo "Plugins deployed successfully!"

- name: Verify plugins deployment
  if: inputs.plugins_local_path != ''
  run: |
    PLUGINS_BUCKET=$(echo "${{ steps.composer.outputs.dags_bucket }}" | sed 's|/dags$|/plugins|')
    echo "Verifying plugins in bucket..."
    gsutil ls -r $PLUGINS_BUCKET/${{ inputs.dags_bucket_subdir }}/
```

### Tag

Bump para `v1.2.0`, atualizar floating tag `v1`.

## Parte 2: Criar repo `data-publishing`

### 2.1 `src/data_publishing/__init__.py`

Vazio.

### 2.2 `src/data_publishing/hf/__init__.py`

Vazio.

### 2.3 `src/data_publishing/hf/schema.py`

Extrair do DAG:
- `HF_COLUMNS` — lista das 24 colunas
- `DATASET_PATH = "nitaibezerra/govbrnews"`
- `REDUCED_DATASET_PATH = "nitaibezerra/govbrnews-reduced"`
- `BRT = timezone(timedelta(hours=-3))`
- `build_arrow_schema()` → `pa.schema` completo (24 campos com tipos timestamp corretos)
- `build_reduced_schema()` → `pa.schema` reduzido (4 campos)
- `records_to_arrow_table(records, columns, schema)` → converte records do PG para `pa.Table`, com tratamento de timestamps (BRT para published_at/updated_datetime, naive para extracted_at)

### 2.4 `src/data_publishing/hf/dedup.py`

Extrair do DAG:
- `HF_API_BASE = "https://datasets-server.huggingface.co"`
- `get_existing_ids_for_date(dataset_path, date_str)` → consulta Dataset Viewer API `/filter`, retorna `set[str]` de unique_ids

### 2.5 `src/data_publishing/hf/uploader.py`

Extrair do DAG:
- `upload_shard(api, table, dataset_path, target_date, timestamp)` → salva parquet temp com snappy, upload via `HfApi.upload_file()`, retorna `shard_name`
- `force_metadata_refresh(api, dataset_path)` → deleta `dataset_info.json`

### 2.6 `src/data_publishing/hf/readme_sanitizer.py`

Extrair do DAG:
- `sanitize_readme(api, repo_id)` → baixa README.md, remove seção `splits:` do YAML front matter, re-upload se modificado

### 2.7 `dags/sync_postgres_to_huggingface.py`

DAG refatorada — mesma lógica, mas importa módulos dos plugins:

```python
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.hooks.base import BaseHook

@dag(...)
def sync_postgres_to_huggingface_dag():
    @task
    def sync_news_to_huggingface(logical_date=None) -> dict:
        from huggingface_hub import HfApi
        from data_publishing.hf.schema import (
            HF_COLUMNS, DATASET_PATH, REDUCED_DATASET_PATH,
            build_arrow_schema, build_reduced_schema,
            records_to_arrow_table, SQL_QUERY,
        )
        from data_publishing.hf.dedup import get_existing_ids_for_date
        from data_publishing.hf.uploader import upload_shard, force_metadata_refresh
        from data_publishing.hf.readme_sanitizer import sanitize_readme

        # ... orquestração (query PG, dedup, upload full + reduced, sanitize)
```

A DAG mantém a query SQL e a lógica de orquestração, mas delega implementação aos módulos.

### 2.8 `dags/requirements.txt`

```
huggingface-hub==0.27.0
pyarrow>=14.0.0
requests>=2.31.0
```

### 2.9 `.github/workflows/composer-deploy-dags.yaml`

```yaml
name: Deploy Publishing DAGs to Composer

on:
  push:
    branches: [main]
    paths:
      - 'dags/**'
      - 'src/data_publishing/**'
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    uses: destaquesgovbr/reusable-workflows/.github/workflows/composer-deploy-dags.yml@v1
    with:
      dags_local_path: dags
      dags_bucket_subdir: data-publishing
      plugins_local_path: src/data_publishing
      check_imports: true
      rsync_exclude: 'requirements\.txt$'
```

**Nota**: trigger inclui `src/data_publishing/**` para re-deploy quando plugins mudam.

### 2.10 `pyproject.toml`

```toml
[tool.poetry]
name = "data-publishing"
version = "0.1.0"
description = "Data publishing pipelines - HuggingFace sync DAGs"
packages = [{include = "data_publishing", from = "src"}]

[tool.poetry.dependencies]
python = "^3.11"
huggingface-hub = ">=0.27.0"
pyarrow = ">=14.0.0"
requests = ">=2.31.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.3"
apache-airflow = ">=3.0.1"
apache-airflow-providers-postgres = "*"
```

### 2.11 `CLAUDE.md` e `README.md`

Documentação do repo.

## Parte 3: Cleanup do `data-platform`

PR separada, após validação do data-publishing:

- Deletar `src/data_platform/dags/sync_postgres_to_huggingface.py`
- Deletar `src/data_platform/dags/requirements.txt`
- Deletar ou simplificar workflow `composer-deploy-dags.yaml` (sem DAGs restantes)

**Manter** no data-platform:
- `managers/dataset_manager.py` — usado por Cogfy pipeline
- `managers/storage_adapter.py` — abstração do Cogfy

## Sequência de Execução

1. **Evoluir reusable workflow** — adicionar input `plugins_local_path`, tag `v1.2.0`
2. **Criar repo** `data-publishing` no GitHub (público, AGPL-3.0)
3. **Criar estrutura** com módulos + DAG refatorada + workflow
4. **Push e deploy** — testar com `workflow_dispatch`
5. **Validar** — DAG no Airflow, trigger manual, shard no HuggingFace
6. **Pausar DAG antiga** no Airflow UI
7. **Aguardar 1 ciclo** (24h) — confirmar nova DAG roda às 6AM UTC
8. **Remover do data-platform** — PR de cleanup

## Verificação

1. Plugins aparecem em `{bucket}/plugins/data-publishing/hf/`
2. DAG `sync_postgres_to_huggingface` aparece no Airflow UI
3. Trigger manual → executa sem erros de import
4. Parquet shard aparece no HuggingFace dataset
5. Dataset reduzido também atualizado
6. Nenhuma DAG duplicada (antiga pausada)
