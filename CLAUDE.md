# DestaquesGovBr Data Platform

> **Última Atualização**: 2026-05-13

---

## O Que É Este Projeto

**Data Platform** é o repositório centralizado de pipelines de dados do DestaquesGovBr — plataforma event-driven que agrega, enriquece e disponibiliza notícias de ~160 sites governamentais brasileiros (gov.br).

### Pipeline (Event-Driven)

```
Scrapers (repo scraper, via Airflow Cloud Composer)
    ↓ Pub/Sub: dgb.news.scraped
    ├── Bronze Writer → GCS (raw JSON)
    ↓
PostgreSQL (Cloud SQL) ← Fonte de verdade (Silver layer)
    ↓ Pub/Sub: dgb.news.enriched
    ├── Feature Worker → news_features (word_count, read_time, etc.)
    ├── Thumbnail Worker → GCS (thumbnails para vídeos)
    ├── Typesense Sync → Typesense (busca textual + semântica)
    ↓ Pub/Sub: dgb.news.embedded
    └── Typesense Sync → Typesense (atualiza embedding)
    ↓
Airflow DAGs (Cloud Composer)
    ├── sync_pg_to_bigquery → BigQuery Gold layer
    ├── compute_trending → trending_score em news_features
    ├── aggregate_engagement → view_count em news_features
    ├── compute_clusters → similar_articles em news_features
    ├── generate_video_thumbnails → Cloud Run thumbnail-worker
    ├── sync_umami_to_bigquery → Analytics em BigQuery
    └── verify_news_integrity → Validação de conteúdo
    ↓
BigQuery (Gold layer) → Portal Web (Next.js)
```

---

## Estrutura do Repositório

```
data-platform/
├── src/data_platform/
│   ├── workers/                    # Cloud Run workers (event-driven)
│   │   ├── bronze_writer/          # dgb.news.scraped → GCS
│   │   │   ├── app.py             # FastAPI entrypoint
│   │   │   ├── handler.py         # Business logic
│   │   │   └── storage.py         # GCS operations
│   │   ├── feature_worker/         # dgb.news.enriched → news_features
│   │   │   ├── app.py
│   │   │   ├── handler.py
│   │   │   └── features.py        # Feature computation
│   │   ├── thumbnail_worker/       # dgb.news.enriched → GCS thumbnails
│   │   │   ├── app.py
│   │   │   ├── handler.py
│   │   │   ├── extractor.py       # Frame extraction (ffmpeg)
│   │   │   └── storage.py
│   │   └── typesense_sync/         # dgb.news.enriched/embedded → Typesense
│   │       ├── app.py
│   │       └── handler.py
│   ├── dags/                       # Airflow DAGs (7 em produção)
│   │   ├── sync_pg_to_bigquery.py
│   │   ├── compute_trending.py
│   │   ├── aggregate_engagement.py
│   │   ├── compute_clusters.py
│   │   ├── generate_video_thumbnails.py
│   │   ├── sync_umami_to_bigquery.py
│   │   └── verify_news_integrity.py
│   ├── jobs/                       # Módulos de processamento
│   │   ├── bigquery/               # sync_to_bigquery, trending, engagement, umami_sync
│   │   ├── enrichment/             # AI enrichment (Bedrock)
│   │   ├── hf_sync/                # HuggingFace sync
│   │   ├── integrity/              # Content verification
│   │   ├── scraper/                # Scraper job utilities
│   │   ├── similarity/             # Article clustering (pgvector)
│   │   ├── thumbnail/              # Thumbnail extraction
│   │   └── typesense/              # Typesense sync jobs
│   ├── managers/                   # Storage managers
│   │   ├── postgres_manager.py     # PostgreSQL (principal)
│   │   ├── dataset_manager.py      # HuggingFace
│   │   └── storage_adapter.py      # Adapter pattern
│   ├── typesense/                  # Typesense client module
│   │   ├── client.py              # Connection management
│   │   ├── collection.py          # Schema definition
│   │   ├── indexer.py             # Document indexing
│   │   └── utils.py
│   ├── models/                     # Pydantic models
│   ├── config.py                   # Centralized settings (pydantic-settings)
│   ├── cli.py                      # Typer CLI
│   └── cloud_run.py                # Cloud Run utilities
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/
│   ├── migrations/                 # Database migrations (001-012)
│   └── bigquery/                   # BigQuery table creation SQL
├── docker/                         # Dockerfiles
│   ├── postgres/                   # PostgreSQL init scripts
│   ├── bronze-writer/
│   ├── feature-worker/
│   ├── thumbnail-worker/
│   └── typesense-sync-worker/
├── .github/workflows/              # CI/CD (10 workflows)
├── docs/                           # Documentation
├── feature_registry.yaml           # Feature definitions (versioned)
├── docker-compose.yml              # Local: PostgreSQL + Typesense
├── Makefile                        # Dev commands (make help)
└── pyproject.toml                  # Dependencies (Poetry, Python ^3.12)
```

---

## Tecnologias

### Backend
- **Python 3.12+** (Poetry)
- **FastAPI** (workers Cloud Run)
- **PostgreSQL 15** (Cloud SQL, pgvector)
- **SQLAlchemy 2.0** + psycopg2

### Data / Analytics
- **Google Cloud BigQuery** (Gold layer)
- **Google Cloud Storage** (Bronze layer)
- **Pandas** / **PyArrow**
- **HuggingFace Datasets**

### Search
- **Typesense** (busca textual + semântica)

### Orchestration
- **Cloud Composer** (Airflow) — 7 DAGs em produção
- **Pub/Sub** — event-driven workers

### Configuration
- **pydantic-settings** (config.py centralizado, `.env` support)
- **feature_registry.yaml** (feature definitions)

### Quality
- **Pytest** + pytest-cov
- **Black** (formatação, line-length 100)
- **Ruff** (linting)
- **MyPy** (type checking, strict)
- **Pre-commit** (obrigatório)

---

## Workers (Cloud Run)

Todos os workers seguem o mesmo padrão: FastAPI app com endpoints `/health` (GET) e `/process` (POST, recebe Pub/Sub push message).

| Worker | Topic | Função | Deploy |
|--------|-------|--------|--------|
| bronze-writer | `dgb.news.scraped` | Raw JSON → GCS `bronze/news/YYYY/MM/DD/{id}.json` | `bronze-writer-deploy.yaml` |
| feature-worker | `dgb.news.enriched` | Computa features → `news_features` JSONB | `feature-worker-deploy.yaml` |
| thumbnail-worker | `dgb.news.enriched` | Gera thumbnails (ffmpeg) para vídeos sem imagem → GCS | `thumbnail-worker-deploy.yaml` |
| typesense-sync | `dgb.news.enriched` + `dgb.news.embedded` | Upsert artigo no Typesense | `typesense-sync-worker-deploy.yaml` |

---

## Airflow DAGs (Cloud Composer)

7 DAGs em produção: `sync_pg_to_bigquery`, `compute_trending`, `aggregate_engagement`, `compute_clusters`, `generate_video_thumbnails`, `sync_umami_to_bigquery`, `verify_news_integrity`.

Deploy automático via `composer-deploy-dags.yaml` ao modificar `src/data_platform/dags/`.

Ver [docs/dags/README.md](docs/dags/README.md) para schedules, Airflow Variables, e detalhes de cada DAG.

---

## BigQuery (Medallion Architecture)

| Camada | Storage | Conteúdo |
|--------|---------|----------|
| Bronze | GCS (`bronze/news/YYYY/MM/DD/`) | Raw JSON do scraper |
| Silver | PostgreSQL Cloud SQL | `news`, `news_features`, `agencies`, `themes` |
| Gold | BigQuery dataset `dgb_gold` | `fato_noticias`, `umami_pageviews`, `umami_events` |

Scripts SQL em `scripts/bigquery/`: `create_tables.sql`, `create_pageviews.sql`, `create_umami_tables.sql`

---

## Feature Registry

Arquivo `feature_registry.yaml` na raiz define todas as features computadas:
- Tipo de dado (`type`)
- Descrição (`description`)
- Modelo/versão (`model`, `version`)
- Quem computa (`compute`: worker ou DAG)

Features são armazenadas na tabela `news_features` (JSONB).

---

## Typesense

Motor de busca para notícias (textual + semântica com embeddings 768-dim).

### CLI

```bash
poetry run data-platform sync-typesense --start-date 2025-01-01
poetry run data-platform typesense-list
poetry run data-platform typesense-delete --confirm
```

### Workflows

| Workflow | Trigger | Descrição |
|----------|---------|-----------|
| `typesense-maintenance-sync.yaml` | Manual | Sync de manutenção |
| `typesense-schema-update.yaml` | Manual | Atualização de schema |
| `typesense-sync-worker-deploy.yaml` | Push to main | Deploy do worker |

---

## Configuração

### Variáveis de Ambiente (config.py)

Gerenciadas via `pydantic-settings` (`src/data_platform/config.py`):

```python
from data_platform.config import get_settings
settings = get_settings()
```

| Variável | Default | Descrição |
|----------|---------|-----------|
| `DATABASE_URL` | `""` | PostgreSQL connection string |
| `TYPESENSE_HOST` | `localhost` | Host do Typesense |
| `TYPESENSE_PORT` | `8108` | Porta |
| `TYPESENSE_PROTOCOL` | `http` | Protocolo |
| `TYPESENSE_API_KEY` | `""` | API key |
| `TYPESENSE_CONNECTION_TIMEOUT_SECONDS` | `10` | Timeout |
| `HF_TOKEN` | `""` | HuggingFace token |
| `HF_REPO_ID` | `destaquesgovbr/govbrnews` | Repo HF |
| `STORAGE_BACKEND` | `postgres` | postgres, huggingface, dual_write |
| `STORAGE_READ_FROM` | `postgres` | postgres, huggingface |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | Modelo |
| `EMBEDDING_BATCH_SIZE` | `32` | Batch size |
| `GCP_PROJECT_ID` | `""` | Projeto GCP |
| `GCS_BUCKET` | `""` | Bucket GCS |
| `LOG_LEVEL` | `INFO` | Nível de log |
| `DEBUG` | `false` | Debug mode |

---

## Schema PostgreSQL

**Tabelas principais**:
- `agencies` — Dados mestres de agências governamentais (158 registros)
- `themes` — Taxonomia hierárquica de temas (3 níveis)
- `news` — Notícias (~300k registros, com embedding pgvector 768-dim)
- `news_features` — Features computadas (JSONB)
- `scrape_runs` — Tracking de execuções de scraping

Ver detalhes em [docs/database/schema.md](docs/database/schema.md).

---

## Desenvolvimento

### Setup

```bash
poetry install
pre-commit install
make docker-up  # PostgreSQL + Typesense locais
cp .env.example .env  # Editar variáveis
```

### Testes

```bash
pytest                    # Todos
pytest tests/unit/        # Unitários
pytest tests/integration/ # Integração (requer DB)
pytest --cov=data_platform
```

### Padrões

- Type hints obrigatórios em todas as funções
- Black (line-length 100)
- Ruff (pycodestyle, pyflakes, isort, bugbear, comprehensions, pyupgrade)
- MyPy strict

### Docker Compose (local)

```bash
make docker-up    # PostgreSQL 15 (porta 5433) + Typesense 27.1 (porta 8108)
make docker-down  # Para serviços
```

---

## CI/CD Workflows

| Workflow | Trigger | Descrição |
|----------|---------|-----------|
| `main-workflow.yaml` | Push/PR | Lint, test, type check |
| `composer-deploy-dags.yaml` | Push `dags/` | Deploy DAGs ao Composer |
| `bronze-writer-deploy.yaml` | Push | Deploy bronze-writer |
| `feature-worker-deploy.yaml` | Push | Deploy feature-worker |
| `thumbnail-worker-deploy.yaml` | Push | Deploy thumbnail-worker |
| `typesense-sync-worker-deploy.yaml` | Push | Deploy typesense-sync |
| `typesense-maintenance-sync.yaml` | Manual | Sync de manutenção |
| `typesense-schema-update.yaml` | Manual | Schema update |
| `db-migrate.yaml` | Manual | Executa migrations |
| `postgres-docker-build.yaml` | Push `docker/postgres/` | Build imagem PG |

---

## Resiliência (Cloud Composer)

- `prevent_destroy=true` no Terraform impede destruição acidental
- CI/CD bloqueia planos que tentam recriar o Composer
- Health check a cada 6h dispara deploy se bucket estiver vazio
- Cross-repo trigger: mudanças no Composer disparam deploy automático

Se DAGs sumirem: `gh workflow run composer-deploy-dags.yaml`

Ver [docs/runbooks/composer-recovery.md](docs/runbooks/composer-recovery.md).

---

## Repositórios Relacionados

| Repositório | Descrição |
|-------------|-----------|
| [destaquesgovbr/infra](https://github.com/destaquesgovbr/infra) | Terraform / GCP (privado) |
| [destaquesgovbr/scraper](https://github.com/destaquesgovbr/scraper) | Scrapers gov.br + EBC |
| [destaquesgovbr/portal](https://github.com/destaquesgovbr/portal) | Frontend Next.js |
| [destaquesgovbr/telegram-bot](https://github.com/destaquesgovbr/telegram-bot) | Bot Telegram |
| [destaquesgovbr/agencies](https://github.com/destaquesgovbr/agencies) | agencies.yaml |
| [destaquesgovbr/themes](https://github.com/destaquesgovbr/themes) | themes_tree.yaml |

---

*Este documento é mantido manualmente. Atualize conforme o projeto evolui.*
