# Airflow DAGs

DAGs em produção no Cloud Composer (southamerica-east1), responsáveis por processamento batch e movimentação de dados entre camadas da arquitetura Medallion.

---

## Visão Geral

| DAG | Schedule | Camada | Descrição |
|-----|----------|--------|-----------|
| `sync_pg_to_bigquery` | `0 7 * * *` | Gold | PG → BigQuery |
| `compute_trending` | `0 */6 * * *` | Gold | Trending scores |
| `aggregate_engagement` | `0 8 * * *` | Gold | Pageview aggregation |
| `compute_clusters` | `30 7 * * *` | Silver | Similarity clustering |
| `generate_video_thumbnails` | `0 */4 * * *` | Silver | Video thumbnails |
| `sync_umami_to_bigquery` | `0 9 * * *` | Gold | Umami → BigQuery |
| `verify_news_integrity` | `*/30 * * * *` | Silver | Content integrity |

---

## Detalhes por DAG

### sync_pg_to_bigquery

Sincroniza dados da tabela `news` para `dgb_gold.fato_noticias` no BigQuery. Registros novos ou atualizados desde a última execução.

- **Tags**: `data-platform`, `bigquery`, `gold`
- **Variables**: `gcp_project_id`, `data_lake_bucket`
- **Job module**: `src/data_platform/jobs/bigquery/sync_to_bigquery.py`

### compute_trending

Calcula trending scores a partir de BigQuery (recência, engajamento, velocidade). Persiste em `news_features.trending_score`.

- **Tags**: `gold`, `features`, `trending`
- **Variables**: `gcp_project_id`
- **Job module**: `src/data_platform/jobs/bigquery/trending.py`

### aggregate_engagement

Agrega pageviews de `dgb_gold.umami_pageviews` por artigo. Persiste em `news_features.view_count`.

- **Tags**: `gold`, `features`, `engagement`
- **Variables**: `gcp_project_id` (sem default — obrigatório)
- **Job module**: `src/data_platform/jobs/bigquery/engagement.py`

### compute_clusters

Encontra artigos similares via cosine similarity (pgvector embeddings 768-dim). Persiste em `news_features.similar_articles`.

- **Tags**: `silver`, `features`, `similarity`
- **Variables**: nenhuma
- **Job module**: `src/data_platform/jobs/similarity/`

### generate_video_thumbnails

Busca artigos com `video_url` sem `image_url` e dispara geração via thumbnail-worker (batch/backfill do processamento event-driven).

- **Tags**: `silver`, `thumbnail`, `video`
- **Variables**: `thumbnail_batch_size`, `thumbnail_worker_url` (obrigatório), `thumbnail_max_workers`
- **Job module**: `src/data_platform/jobs/thumbnail/`

### sync_umami_to_bigquery

Exporta pageviews e custom events do Umami (PostgreSQL) para BigQuery (`dgb_gold.umami_pageviews`, `dgb_gold.umami_events`).

- **Tags**: `data-platform`, `bigquery`, `umami`, `analytics`
- **Variables**: `gcp_project_id`
- **Job module**: `src/data_platform/jobs/bigquery/umami_sync.py`

### verify_news_integrity

Valida que artigos recentes possuem imagens acessíveis e conteúdo íntegro. Usa API do scraper para re-verificar URLs.

- **Tags**: `silver`, `integrity`, `quality`
- **Variables**: `integrity_batch_size`, `scraper_api_url` (obrigatório)
- **Job module**: `src/data_platform/jobs/integrity/`

---

## Infraestrutura

### Airflow Connection

| Connection ID | Tipo | Descrição |
|---------------|------|-----------|
| `postgres_default` | PostgreSQL | Cloud SQL principal |

### Airflow Variables

| Key | Default | Obrigatório | Usado por |
|-----|---------|-------------|-----------|
| `gcp_project_id` | `inspire-7-finep` | Sim* | sync_pg_to_bigquery, compute_trending, sync_umami_to_bigquery, aggregate_engagement |
| `data_lake_bucket` | `inspire-7-finep-dgb-data-lake` | Não | sync_pg_to_bigquery |
| `integrity_batch_size` | `400` | Não | verify_news_integrity |
| `scraper_api_url` | — | Sim | verify_news_integrity |
| `thumbnail_batch_size` | `100` | Não | generate_video_thumbnails |
| `thumbnail_worker_url` | — | Sim | generate_video_thumbnails |
| `thumbnail_max_workers` | `5` | Não | generate_video_thumbnails |

*`aggregate_engagement` usa `gcp_project_id` sem default — falhará se a Variable não existir.

---

## Deploy

Workflow: `.github/workflows/composer-deploy-dags.yaml`

```bash
# Automático: push em src/data_platform/dags/ dispara deploy
# Manual:
gh workflow run composer-deploy-dags.yaml
```

O deploy usa `gsutil rsync -r -d` para o subdiretório `data-platform/` do bucket de DAGs. Ver [Decentralized DAGs](../architecture/decentralized-dags.md) para convenção completa.

---

## Código

```
src/data_platform/dags/
├── sync_pg_to_bigquery.py
├── compute_trending.py
├── aggregate_engagement.py
├── compute_clusters.py
├── generate_video_thumbnails.py
├── sync_umami_to_bigquery.py
└── verify_news_integrity.py
```

DAGs importam jobs de `src/data_platform/jobs/` para a lógica de processamento. Todas usam o decorator `@dag` do Airflow TaskFlow API e `owner: "data-platform"` nos default_args.
