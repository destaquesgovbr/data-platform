# DestaquesGovBr Data Platform

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 15](https://img.shields.io/badge/postgresql-15-blue.svg)](https://www.postgresql.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> Plataforma de dados event-driven para agregação, enriquecimento e disponibilização de notícias governamentais brasileiras, com arquitetura Medallion (Bronze/Silver/Gold).

📚 **[Ver Documentação Completa](docs/README.md)** | 🗃️ **[Dataset Público](https://huggingface.co/datasets/nitaibezerra/govbrnews)**

---

## Sobre o Projeto

A **Data Platform** centraliza toda a infraestrutura de dados do [DestaquesGovBr](https://destaques.gov.br):

- Recepção de eventos de scraping via Pub/Sub
- Armazenamento raw em GCS (Bronze layer) e PostgreSQL (Silver layer)
- Enriquecimento com IA (classificação temática, sumários) via AWS Bedrock
- Geração de embeddings (768-dim) para busca semântica
- Computação de features (trending, engagement, similaridade, thumbnails)
- Indexação para busca (Typesense)
- Agregação analítica em BigQuery (Gold layer)
- Sincronização com HuggingFace (dados abertos)

---

## Arquitetura

```
Scrapers (repo scraper, via Airflow)
    ↓ Pub/Sub: dgb.news.scraped
    ↓
┌──────────────────────────────────────────────────────────────────┐
│                        Cloud Run Workers                          │
├──────────────────┬───────────────┬──────────────┬────────────────┤
│ Bronze Writer    │ Feature Worker│ Thumbnail    │ Typesense Sync │
│ → GCS raw JSON   │ → news_features│ Worker       │ → Typesense    │
│                  │               │ → GCS thumbs │                │
└──────────────────┴───────────────┴──────────────┴────────────────┘
    ↑ Pub/Sub: dgb.news.enriched / dgb.news.embedded
    │
Enriquecimento IA (Bedrock) + Embeddings
    ↑
PostgreSQL (Cloud SQL) ← Fonte de verdade (Silver)
    ↓
┌──────────────────────────────────────────────────────────────────┐
│                     Airflow DAGs (Composer)                       │
├─────────────────┬──────────────┬─────────────────────────────────┤
│ sync_pg_to_     │ compute_     │ aggregate_engagement            │
│ bigquery        │ trending     │ compute_clusters                │
│                 │              │ generate_video_thumbnails       │
│ sync_umami_to_  │ verify_news_ │                                 │
│ bigquery        │ integrity    │                                 │
└─────────────────┴──────────────┴─────────────────────────────────┘
    ↓
BigQuery (Gold layer) ← Dados analíticos
    ↓
Portal Web (Next.js)
```

---

## Estrutura do Repositório

```
data-platform/
├── src/data_platform/
│   ├── workers/              # Cloud Run workers (event-driven)
│   │   ├── bronze_writer/    # GCS raw JSON storage
│   │   ├── feature_worker/   # Feature computation
│   │   ├── thumbnail_worker/ # Video thumbnail generation
│   │   └── typesense_sync/   # Search index sync
│   ├── dags/                 # Airflow DAGs (7 em produção)
│   ├── jobs/                 # Job modules
│   │   ├── bigquery/         # PG→BigQuery, trending, engagement, umami
│   │   ├── enrichment/       # AI enrichment
│   │   ├── embeddings/       # Embedding generation
│   │   ├── integrity/        # Content verification
│   │   ├── similarity/       # Article clustering
│   │   ├── thumbnail/        # Thumbnail extraction
│   │   ├── typesense/        # Typesense sync
│   │   └── hf_sync/          # HuggingFace sync
│   ├── managers/             # Storage managers (PostgreSQL, HF)
│   ├── models/               # Pydantic models
│   ├── typesense/            # Typesense client/collection/indexer
│   └── config.py             # Centralized settings (pydantic-settings)
├── tests/                    # Unit + integration tests
├── scripts/
│   ├── migrations/           # Database migrations (001-012)
│   └── bigquery/             # BigQuery table creation SQL
├── docker/                   # Dockerfiles for workers
├── docs/                     # Documentation
├── .github/workflows/        # CI/CD workflows
├── feature_registry.yaml     # Feature definitions (versioned)
├── docker-compose.yml        # Local dev (PostgreSQL + Typesense)
├── Makefile                  # Development commands
└── pyproject.toml            # Dependencies (Poetry)
```

---

## Workers (Cloud Run)

| Worker | Pub/Sub Topic | Função | Deploy Workflow |
|--------|---------------|--------|-----------------|
| **bronze-writer** | `dgb.news.scraped` | Grava raw JSON em GCS Bronze layer | `bronze-writer-deploy.yaml` |
| **feature-worker** | `dgb.news.enriched` | Computa features locais → `news_features` | `feature-worker-deploy.yaml` |
| **thumbnail-worker** | `dgb.news.enriched` | Gera thumbnails para vídeos sem imagem | `thumbnail-worker-deploy.yaml` |
| **typesense-sync** | `dgb.news.enriched`, `dgb.news.embedded` | Upsert em Typesense | `typesense-sync-worker-deploy.yaml` |

---

## Airflow DAGs (Cloud Composer)

| DAG | Schedule | Camada | Descrição |
|-----|----------|--------|-----------|
| `sync_pg_to_bigquery` | Diário 7 AM | Gold | Sincroniza PG → BigQuery |
| `compute_trending` | A cada 6h | Gold | Calcula trending scores |
| `aggregate_engagement` | Diário 8 AM | Gold | Agrega pageviews (view_count) |
| `compute_clusters` | Diário 7:30 AM | Silver | Clustering por similaridade (pgvector) |
| `generate_video_thumbnails` | `0 */4 * * *` | Silver | Gera thumbnails de vídeo |
| `sync_umami_to_bigquery` | Diário 9 AM | Gold | Umami analytics → BigQuery |
| `verify_news_integrity` | A cada 30 min | Silver | Verifica integridade de conteúdo |

Deploy: `composer-deploy-dags.yaml` (automático ao modificar `src/data_platform/dags/`)

---

## BigQuery (Medallion Architecture)

| Camada | Storage | Conteúdo |
|--------|---------|----------|
| **Bronze** | GCS (`bronze/news/YYYY/MM/DD/`) | Raw JSON dos scrapers |
| **Silver** | PostgreSQL (Cloud SQL) | Tabelas normalizadas: `news`, `news_features`, `agencies`, `themes` |
| **Gold** | BigQuery (`dgb_gold`) | `fato_noticias`, `umami_pageviews`, `umami_events` |

---

## Feature Registry

O arquivo `feature_registry.yaml` na raiz define todas as features computadas, incluindo:
- Quem computa (worker/DAG)
- Tipo de dado
- Modelo/versão
- Schedule de atualização

---

## Quick Start

### Pré-requisitos

- Python 3.12+
- Poetry
- Docker (para PostgreSQL + Typesense locais)

### Instalação

```bash
git clone https://github.com/destaquesgovbr/data-platform.git
cd data-platform

# Instalar dependências
poetry install

# Instalar pre-commit hooks (obrigatório)
pre-commit install

# Subir serviços locais (PostgreSQL + Typesense)
make docker-up

# Ver todos os comandos disponíveis
make help
```

### Executar Testes

```bash
# Todos os testes
pytest

# Apenas unitários
pytest tests/unit/

# Apenas integração
pytest tests/integration/
```

---

## Padrões de Código

- **Type hints**: Obrigatórios em todas as funções
- **Formatação**: Black (linha máxima 100)
- **Linting**: Ruff
- **Type checking**: MyPy (strict)
- **Pre-commit**: Roda automaticamente Black, Ruff e MyPy

```bash
# Rodar manualmente
make lint    # ou: poetry run ruff check src/ tests/
make format  # ou: poetry run black src/ tests/
```

---

## Documentação

| Documento | Descrição |
|-----------|-----------|
| [docs/README.md](./docs/README.md) | Índice completo |
| [docs/architecture/overview.md](./docs/architecture/overview.md) | Arquitetura do sistema |
| [docs/database/schema.md](./docs/database/schema.md) | Schema PostgreSQL |
| [docs/database/migrations.md](./docs/database/migrations.md) | Migrações (001-012) |
| [docs/development/setup.md](./docs/development/setup.md) | Setup do ambiente |
| [docs/typesense/](./docs/typesense/) | Typesense (busca) |
| [docs/runbooks/](./docs/runbooks/) | Runbooks operacionais |

---

## Repositórios Relacionados

| Repositório | Descrição |
|-------------|-----------|
| [destaquesgovbr/infra](https://github.com/destaquesgovbr/infra) | Terraform / GCP (privado) |
| [destaquesgovbr/scraper](https://github.com/destaquesgovbr/scraper) | Scrapers gov.br + EBC (Airflow + Cloud Run) |
| [destaquesgovbr/portal](https://github.com/destaquesgovbr/portal) | Frontend Next.js |
| [destaquesgovbr/telegram-bot](https://github.com/destaquesgovbr/telegram-bot) | Bot Telegram |

---

## Dados Abertos

- **Dataset completo**: [nitaibezerra/govbrnews](https://huggingface.co/datasets/nitaibezerra/govbrnews)
- **Dataset reduzido**: [nitaibezerra/govbrnews-reduced](https://huggingface.co/datasets/nitaibezerra/govbrnews-reduced)

---

## Licença

GPLv3 - ver [LICENSE](LICENSE) para detalhes.

---

*Última atualização: 2026-05-13*
