# Plano: Extrair Scraper para Repo Standalone

## Contexto

O scraper de notícias gov.br está todo dentro do repo `data-platform`, junto com código de enriquecimento, Typesense, HuggingFace sync, etc. Queremos descentralizar: criar um repo `scraper` standalone com todo o código de scraping (API, DAGs, scrapers, storage), e estabelecer uma convenção de deploy de DAGs por subdiretório para suportar múltiplos repos.

## Arquitetura Alvo

```
Repo scraper/                        Repo data-platform/
  dags/ → {bucket}/scraper/            dags/ → {bucket}/data-platform/
    scrape_agencies.py                   sync_postgres_to_huggingface.py
    scrape_ebc.py                        test_postgres_connection.py
    config/site_urls.yaml
  src/govbr_scraper/                   src/data_platform/
    api.py (FastAPI)                     managers/ (shared, stays)
    scrapers/                            models/ (shared, stays)
    storage/ (postgres-only copy)        cogfy/, typesense/, etc.
```

## Sequência de Migração (sem downtime)

| Passo | Repo | Ação | Risco |
|-------|------|------|-------|
| 1 | infra | Adicionar WI binding para repo `scraper` | Nenhum |
| 2 | data-platform | Mudar DAG deploy para subdiretório `{bucket}/data-platform/` + limpar DAGs raiz | **Crítico**: DAGs duplicadas se não limpar |
| 3 | scraper (novo) | Criar repo, copiar código, deploy API + DAGs para `{bucket}/scraper/` | Nenhum (aditivo) |
| 4 | data-platform | Remover código do scraper | Cleanup |

## Passo 1: Infra — WI Binding

**Arquivo**: `infra/terraform/workload-identity.tf`

Adicionar binding para o novo repo (seguindo padrão existente):

```hcl
resource "google_service_account_iam_member" "github_actions_workload_identity_scraper" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_organization}/scraper"
}
```

Sem outras mudanças no infra — o Cloud Run service, SA, IAM, Artifact Registry já existem.

## Passo 2: data-platform — Deploy DAGs para Subdiretório

**Arquivo**: `data-platform/.github/workflows/composer-deploy-dags.yaml`

Mudanças:
1. `gsutil rsync` target: `${{ steps.composer.outputs.dags_bucket }}/` → `${{ steps.composer.outputs.dags_bucket }}/data-platform/`
2. Adicionar step de limpeza ONE-TIME dos DAGs na raiz (evitar duplicatas):

```yaml
- name: Clean up legacy root-level DAGs
  run: |
    BUCKET="${{ steps.composer.outputs.dags_bucket }}"
    for f in scrape_agencies.py scrape_ebc.py sync_postgres_to_huggingface.py test_postgres_connection.py; do
      gsutil rm "$BUCKET/$f" 2>/dev/null || true
    done
    gsutil rm -r "$BUCKET/config/" 2>/dev/null || true
```

3. Remover DAGs do scraper do diretório de DAGs do data-platform:
   - Deletar `src/data_platform/dags/scrape_agencies.py`
   - Deletar `src/data_platform/dags/scrape_ebc.py`
   - Deletar `src/data_platform/dags/config/` (site_urls.yaml)

DAGs que ficam: `sync_postgres_to_huggingface.py`, `test_postgres_connection.py`

## Passo 3: Criar Repo `scraper`

### Estrutura

```
scraper/
├── src/govbr_scraper/
│   ├── __init__.py           # Configura loguru level
│   ├── api.py                # FastAPI (copy de data_platform.api)
│   ├── config.py             # Settings simplificado (só DB)
│   ├── scrapers/
│   │   ├── webscraper.py          # Copy as-is (sem imports de data_platform)
│   │   ├── scrape_manager.py      # Copy, update imports
│   │   ├── ebc_webscraper.py      # Copy as-is
│   │   ├── ebc_scrape_manager.py  # Copy, update imports
│   │   └── config/site_urls.yaml
│   ├── storage/
│   │   ├── storage_adapter.py     # Simplificado (postgres-only, sem HF/dual-write)
│   │   └── postgres_manager.py    # Copy, update imports
│   └── models/
│       └── news.py                # Copy NewsInsert, Agency, Theme
├── dags/
│   ├── scrape_agencies.py         # Copy, owner="scraper"
│   ├── scrape_ebc.py              # Copy, owner="scraper"
│   └── config/site_urls.yaml
├── tests/
│   └── unit/test_ebc_scraper.py
├── docker/Dockerfile
├── .github/workflows/
│   ├── scraper-api-deploy.yaml    # Build + deploy Cloud Run
│   ├── composer-deploy-dags.yaml  # Deploy DAGs → {bucket}/scraper/
│   └── tests.yaml                 # pytest on PR
├── pyproject.toml
├── CLAUDE.md
└── .gitignore
```

### Import Changes

| Arquivo | Import antigo | Import novo |
|---------|--------------|-------------|
| api.py | `data_platform.managers.StorageAdapter` | `govbr_scraper.storage.StorageAdapter` |
| api.py | `data_platform.scrapers.scrape_manager` | `govbr_scraper.scrapers.scrape_manager` |
| api.py | `data_platform.scrapers.ebc_scrape_manager` | `govbr_scraper.scrapers.ebc_scrape_manager` |
| postgres_manager.py | `data_platform.models.news` | `govbr_scraper.models.news` |
| storage_adapter.py | `data_platform.managers.postgres_manager` | `govbr_scraper.storage.postgres_manager` |
| storage_adapter.py | `data_platform.models.news` | `govbr_scraper.models.news` |

### StorageAdapter Simplificado

Remover: HuggingFace backend, dual-write, `get()`, `update()`, `STORAGE_READ_FROM`. Manter apenas `insert()` com path postgres.

### pyproject.toml (deps)

```
python ^3.12
psycopg2-binary, sqlalchemy          # DB
fastapi, uvicorn                     # API
beautifulsoup4, requests, retry, markdownify  # Scraping
numpy, scipy                         # EBC smart_sleep
pydantic, pydantic-settings, pyyaml  # Config
loguru                               # Logging
```

Nota: `pandas` NÃO é necessário (era só para HF paths).

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential gcc libpq-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir poetry
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && poetry install --no-root --no-interaction
COPY src/ src/
RUN poetry install --no-interaction
EXPOSE 8080
CMD ["uvicorn", "govbr_scraper.api:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Workflow: composer-deploy-dags.yaml

Baseado no de data-platform, com:
- `DAGS_LOCAL_PATH: dags`
- rsync target: `${{ steps.composer.outputs.dags_bucket }}/scraper/`
- Sem step de "Clean stale plugins"

### Workflow: scraper-api-deploy.yaml

Copy do data-platform, ajustando paths de trigger para `src/govbr_scraper/**`, `docker/**`.

## Passo 4: Cleanup do data-platform

**Deletar**:
- `src/data_platform/api.py`
- `src/data_platform/scrapers/` (inteiro)
- `docker/scraper-api/`
- `.github/workflows/scraper-api-deploy.yaml`
- `tests/unit/test_ebc_scraper.py`
- `tests/integration/test_ebc_scraper_live.py`

**Atualizar**:
- `pyproject.toml`: remover deps exclusivas do scraper (beautifulsoup4, markdownify, retry, fastapi, uvicorn, scipy)
- `cli.py`: remover comandos `scrape` e `scrape-ebc`

**Manter**: `managers/`, `models/`, `config.py` (usados por enrichment, typesense, HF sync)

## Verificação

1. **Pós passo 2**: Airflow UI mostra DAGs em `data-platform/` (sync_pg_to_hf, test_pg_conn). Sem duplicatas.
2. **Pós passo 3**: Airflow UI mostra DAGs em `scraper/` (155 scrape_* + scrape_ebc). Trigger manual de 1 DAG → 200 OK.
3. **Pós passo 4**: `data-platform` não tem mais código de scraper. Pipeline diário (cogfy → enrich → embeddings → typesense) continua funcionando.
4. Cloud Run service continua o mesmo, agora deployado pelo repo `scraper`.
