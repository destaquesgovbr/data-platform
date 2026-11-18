# Airflow DAGs

DAGs em produção no Cloud Composer (southamerica-east1), responsáveis por processamento batch e movimentação de dados entre camadas da arquitetura Medallion.

---

## Visão Geral

| DAG | Schedule | Camada | Descrição |
|-----|----------|--------|-----------|
| `sync_pg_to_bigquery` | `0 7 * * *` | Gold | PG → BigQuery |
| `compute_trending` | `0 */6 * * *` | Gold | Trending scores |
| `aggregate_engagement` | `0 8 * * *` | Gold | Pageview aggregation + Flesch pt-BR faltante |
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

Task independente `fill_flesch_ptbr` (DP-1c): completa `news_features.readability_flesch_ptbr` nas
linhas tocadas nos últimos 3 dias (`updated_at`) que têm `content` e não têm a chave. O
feature-worker grava a chave em todo artigo que processa; `enrichment_backfill` e o ner-backfill
criam ou reescrevem linhas sem ela. Mesmo cálculo do worker
(`src/data_platform/jobs/features/readability_ptbr.py`), merge no JSONB e commit por lote.

- **Job module**: `src/data_platform/jobs/features/flesch_ptbr_fill.py`
- **Plugins**: o `composer-deploy-dags` instala o `pyphen` da versão do `poetry.lock` em
  `plugins/pyphen/` (o ambiente não tem o pacote).
- **Varredura completa** (manual): `dags trigger aggregate_engagement --conf '{"flesch_lookback_days": null}'`.

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
# Automático: push em src/data_platform/{dags,jobs,typesense}/, cloud_run.py, poetry.lock
# ou no próprio workflow dispara deploy
# Manual:
gh workflow run composer-deploy-dags.yaml
```

Desde a Fase 3 da migração do Composer o deploy publica nos dois buckets, o do Composer
(`southamerica-east1-destaque-227e22da-bucket`) e o do Airflow próprio (`destaquesgovbr-airflow`),
com `gcloud storage rsync --recursive --delete-unmatched-destination-objects`:

1. **Plugins** (job `deploy-plugins`, primeiro): `plugins/data_platform/` (os módulos de
   `jobs/`, `typesense/` e `cloud_run.py` importados pelas DAGs) e `plugins/pyphen/`, em cada
   bucket de `AIRFLOW_DAG_BUCKETS` (env do workflow), depois de um `py_compile` (Python 3.11)
   das DAGs e dos plugins.
2. **DAGs** (job `deploy-dags`, depois dos plugins): `dags/data-platform/` via
   `reusable-workflows/.github/workflows/airflow-deploy-dags.yml@v3`, que recebe a mesma lista
   (output `buckets` do job de plugins; o default de `buckets` do v3 não vale aqui).

`AIRFLOW_DAG_BUCKETS` é a única lista do deploy. Um deploy roda por vez (grupo de concorrência
`data-platform-airflow-deploy`): o em andamento termina e só o mais novo espera na fila.

A validação completa do v3 (Airflow 3.1.8 com constraints) roda com os plugins já publicados.
Se ela falhar (ex.: na instalação do Airflow), os plugins novos ficam nos buckets com as DAGs
antigas: rodar de novo os jobs que falharam (`gh run rerun <id> --failed`) logo em seguida.

Na Fase 7 (desligar o Composer) o bucket do Composer sai de `AIRFLOW_DAG_BUCKETS`, **antes** de o
bucket ser apagado: com o bucket na lista e já apagado o rsync dos plugins falha e as DAGs não são
publicadas em lugar nenhum. No Airflow próprio as DAGs nascem pausadas
(`dags_are_paused_at_creation=True`) e só são despausadas na virada (Fase 5).

Ver [Decentralized DAGs](../architecture/decentralized-dags.md) para convenção completa.

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
