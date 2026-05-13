# Architecture Overview

High-level architecture of the DestaquesGovBr Data Platform.

---

## System Context

The Data Platform is an event-driven system that processes Brazilian government news through a Medallion architecture (Bronze/Silver/Gold), using Pub/Sub for async communication between Cloud Run workers.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DestaquesGovBr Ecosystem                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Scraper (Cloud Run)                                                │
│  ~160 agencies                                                      │
│       │                                                             │
│       ↓ Pub/Sub: dgb.news.scraped                                   │
│       │                                                             │
│  ┌────┴──────────────────────────────────────────────────────┐      │
│  │              Cloud Run Workers                             │      │
│  │  ┌─────────────┬─────────────┬──────────┬─────────────┐  │      │
│  │  │Bronze Writer│Feature Wkr  │Thumbnail │Typesense    │  │      │
│  │  │→ GCS        │→ PG features│Wkr → GCS │Sync → Index │  │      │
│  │  └─────────────┴─────────────┴──────────┴─────────────┘  │      │
│  └───────────────────────────────────────────────────────────┘      │
│       ↑ Pub/Sub: dgb.news.enriched / dgb.news.embedded              │
│       │                                                             │
│  PostgreSQL (Cloud SQL)      Bedrock (LLM)                          │
│  Silver layer                 → themes + summaries                  │
│       │                                                             │
│       ↓ Airflow DAGs (Cloud Composer)                               │
│       │                                                             │
│  BigQuery (Gold layer)       Typesense         HuggingFace          │
│  Analytics/trending          Search            Open Data            │
│       │                                                             │
│       ↓                                                             │
│  Portal Web (Next.js)                                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Medallion Architecture

### Bronze Layer (GCS)

Raw data as received from scrapers, stored as JSON in GCS:
- Path: `gs://{bucket}/bronze/news/YYYY/MM/DD/{unique_id}.json`
- Written by: **bronze-writer** worker
- Triggered by: `dgb.news.scraped` Pub/Sub topic

### Silver Layer (PostgreSQL)

Normalized, enriched data in Cloud SQL:
- `news` — Articles (~300k records, pgvector embedding 768-dim)
- `news_features` — Computed features (JSONB: trending_score, view_count, similar_articles, etc.)
- `agencies` — Government agencies (158 records)
- `themes` — Theme taxonomy (3-level hierarchy)
- `scrape_runs` — Scraping execution tracking

### Gold Layer (BigQuery)

Analytical tables for dashboards and trending computation:
- `dgb_gold.fato_noticias` — Denormalized news facts
- `dgb_gold.umami_pageviews` — Portal pageview analytics
- `dgb_gold.umami_events` — Custom event analytics

SQL scripts de criação em `scripts/bigquery/`: `create_tables.sql`, `create_pageviews.sql`, `create_umami_tables.sql`.

Note: dados fluem de Gold de volta para Silver — DAGs `compute_trending` e `aggregate_engagement` calculam no BigQuery e persistem resultado em `news_features` (PostgreSQL).

---

## Workers (Cloud Run)

4 workers in production, all following the same pattern: FastAPI app with `/health` (GET) and `/process` (POST) endpoints, receiving Pub/Sub push messages. Each worker decodes the message, fetches the full article from PostgreSQL, processes it, and returns 200 (ack) or 4xx/5xx (nack → Pub/Sub retry).

See [Workers documentation](../workers/README.md) for details on each worker, topics, and deploy workflows.

---

## Airflow DAGs (Cloud Composer)

7 DAGs in production, orchestrated by Cloud Composer (southamerica-east1). They handle batch processing and data movement between Medallion layers (Silver↔Gold).

Deploy: `composer-deploy-dags.yaml` (triggered on push to `src/data_platform/dags/`)

See [DAGs documentation](../dags/README.md) for schedules, variables, and details on each DAG.

---

## Feature Registry

Features are defined in `feature_registry.yaml` at the repo root. Each feature specifies:
- Compute source (worker or DAG)
- Data type and default value
- Model/version
- Update schedule

Features are stored in `news_features` table (JSONB per article).

---

## Event Flow (Pub/Sub Topics)

| Topic | Publisher | Subscribers | Payload |
|-------|-----------|-------------|---------|
| `dgb.news.scraped` | Scraper (Cloud Run) | bronze-writer | `{unique_id, agency_key}` |
| `dgb.news.enriched` | Enrichment pipeline | feature-worker, thumbnail-worker, typesense-sync | `{unique_id}` |
| `dgb.news.embedded` | Embedding pipeline | typesense-sync | `{unique_id}` |

Workers recebem push subscriptions (HTTP POST para `/process`) com message base64-encoded. Retry com exponential backoff gerenciado pelo Pub/Sub.

---

## Technology Stack

### Backend
- **Language**: Python 3.12+
- **Web Framework**: FastAPI (workers)
- **Database**: PostgreSQL 15 (Cloud SQL) with pgvector
- **ORM**: SQLAlchemy 2.0
- **Config**: pydantic-settings

### Data Processing
- **Analytics**: Google Cloud BigQuery
- **Object Storage**: Google Cloud Storage
- **Data**: Pandas, PyArrow
- **LLM**: AWS Bedrock (themes + summaries)
- **Embeddings**: sentence-transformers (768-dim)

### Search
- **Typesense**: Full-text + semantic search (embeddings)

### Infrastructure
- **Cloud**: Google Cloud Platform
- **IaC**: Terraform (repo: destaquesgovbr/infra)
- **Orchestration**: Cloud Composer (Airflow)
- **Messaging**: Pub/Sub
- **CI/CD**: GitHub Actions (10 workflows)

### Development
- **Package Manager**: Poetry
- **Testing**: pytest
- **Linting**: Ruff, Black (line-length 100)
- **Type Checking**: mypy (strict)
- **Hooks**: pre-commit

---

## Design Principles

### 1. Event-Driven Processing
Workers subscribe to Pub/Sub topics and process messages independently. This allows:
- Independent scaling per worker
- Retry with exponential backoff (Pub/Sub managed)
- Adding new consumers without changing publishers

### 2. Medallion Architecture
Data flows through Bronze → Silver → Gold layers with increasing quality and structure:
- Bronze: immutable raw data (audit trail)
- Silver: normalized operational data
- Gold: denormalized analytical data

### 3. Feature Registry
Centralized definition of computed features prevents drift between documentation and code. The registry is the source of truth for what features exist and how they're computed.

### 4. Data Integrity
- Unique constraint on `unique_id`
- Foreign key constraints (agencies, themes)
- Periodic integrity verification (DAG: verify_news_integrity)
- Content hashing for deduplication

---

## Security

### Authentication
- GCP service accounts per worker
- Workload Identity Federation (GitHub Actions → GCP)
- Cloud SQL Proxy for secure database connections

### Secrets Management
- All credentials in GCP Secret Manager
- No secrets in code or config files
- Workers access secrets via environment injection at deploy

### Network
- Private IP for Cloud SQL
- VPC peering with Service Networking
- Pub/Sub push endpoints authenticated via IAM

---

## Resilience

### Cloud Composer
- `prevent_destroy=true` in Terraform
- Health check every 6h auto-deploys if bucket is empty
- Cross-repo trigger on Composer changes

### Workers
- Pub/Sub retry with exponential backoff
- Dead-letter topics for failed messages
- Health check endpoints for Cloud Run auto-restart

### Database
- Automated backups (30 days retention)
- Point-in-time recovery (7 days)
- Deletion protection enabled

---

See also:
- [Database Schema](../database/schema.md)
- [Development Setup](../development/setup.md)
- [Typesense](../typesense/README.md)
- [Composer Recovery Runbook](../runbooks/composer-recovery.md)
