# Arquitetura de Dados DGB — Plano de Implementação Detalhado

## Visão Geral

Evolução da arquitetura de dados do DGB com padrão Medallion (Bronze/Silver/Gold) e Feature Store JSONB. Decisão documentada no [ADR-001](https://destaquesgovbr.github.io/docs/arquitetura/adrs/adr-001-arquitetura-dados-medallion/).

```
┌─────────────────────────────────────────────────────────────────────┐
│  BRONZE — GCS bucket (dados brutos imutáveis, JSON particionado)    │
├─────────────────────────────────────────────────────────────────────┤
│  SILVER — PostgreSQL (news + news_features JSONB) + Typesense       │
├─────────────────────────────────────────────────────────────────────┤
│  GOLD — BigQuery (fato_noticias, dimensões, métricas, trending)     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Fase 0 — Fundação

**Objetivo**: Preparar infraestrutura base sem alterar nada operacional.
**Custo incremental**: $0
**Repos afetados**: `data-platform`, `infra`

### 0.1 — Criar tabela `news_features` (migration SQL)

**Repo**: `data-platform`
**Arquivo**: `scripts/migrations/004_create_news_features.sql`

Segue padrão das migrations existentes (001–003 em `scripts/migrations/`).

```sql
-- 004_create_news_features.sql
-- Feature Store: armazena features computadas para cada notícia (JSONB flexível)

CREATE TABLE IF NOT EXISTS news_features (
    unique_id VARCHAR(32) PRIMARY KEY REFERENCES news(unique_id) ON DELETE CASCADE,
    features JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Índice GIN para queries em campos específicos do JSONB
-- Ex: SELECT * FROM news_features WHERE features @> '{"sentiment": {"label": "positive"}}'
CREATE INDEX IF NOT EXISTS idx_news_features_gin ON news_features USING GIN (features);

-- Índice para ordenação por data de atualização
CREATE INDEX IF NOT EXISTS idx_news_features_updated_at ON news_features (updated_at DESC);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_news_features_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_news_features_updated_at
    BEFORE UPDATE ON news_features
    FOR EACH ROW
    EXECUTE FUNCTION update_news_features_updated_at();
```

**unique_id é VARCHAR(32)** (não TEXT) — consistente com a tabela `news`.

**Execução**:
```bash
psql "$DATABASE_URL" -f scripts/migrations/004_create_news_features.sql
```

**Teste**: `data-platform/tests/unit/test_news_features_migration.py`
```python
# Verificar que a migration é idempotente (IF NOT EXISTS)
# Verificar que o trigger funciona (updated_at auto-atualizado)
# Verificar que o índice GIN funciona para @> queries
# Verificar FK cascade (deletar news → deleta news_features)
```

### 0.2 — Adicionar métodos ao PostgresManager

**Repo**: `data-platform`
**Arquivo**: `src/data_platform/managers/postgres_manager.py` (editar)

Adicionar 3 métodos seguindo o padrão existente (context manager `get_connection/put_connection`, `cursor`, `commit/rollback`):

```python
def upsert_features(self, unique_id: str, features: dict[str, Any]) -> bool:
    """Merge features into news_features (JSONB || operator).

    Faz merge (não substitui): features existentes são preservadas,
    novas são adicionadas, chaves iguais são sobrescritas.

    INSERT ... ON CONFLICT (unique_id) DO UPDATE SET
        features = news_features.features || EXCLUDED.features
    """

def get_features(self, unique_id: str) -> dict[str, Any] | None:
    """Retorna features de um artigo ou None se não existir."""

def get_features_batch(self, unique_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Retorna features de múltiplos artigos. {unique_id: features_dict}."""
```

**Teste**: `data-platform/tests/unit/test_postgres_manager_features.py`
```python
# test_upsert_features_insert — primeira inserção
# test_upsert_features_merge — merge preserva features existentes
# test_upsert_features_overwrite_key — mesma chave sobrescreve valor
# test_get_features_existing — artigo com features
# test_get_features_nonexistent — retorna None
# test_get_features_batch — múltiplos artigos
# test_get_features_batch_partial — alguns existem, outros não
```

### 0.3 — Criar modelo Pydantic `NewsFeatures`

**Repo**: `data-platform`
**Arquivo**: `src/data_platform/models/news.py` (editar — adicionar ao final)

```python
class NewsFeatures(BaseModel):
    unique_id: str
    features: dict[str, Any] = {}
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

### 0.4 — Criar Feature Registry

**Repo**: `data-platform`
**Arquivo**: `feature_registry.yaml` (novo, na raiz do repo)

```yaml
# Feature Registry — controle de versões das features computadas
# Cada feature tem: versão, modelo usado, e onde é computada.
# Isso permite reprocessamento seletivo quando um modelo muda.

features:
  # --- Fase 1: Features locais (sem IA) ---
  word_count:
    version: "1.0"
    type: integer
    description: "Contagem de palavras do conteúdo"
    model: "local/python"
    compute: "feature-worker"

  char_count:
    version: "1.0"
    type: integer
    description: "Contagem de caracteres do conteúdo"
    model: "local/python"
    compute: "feature-worker"

  paragraph_count:
    version: "1.0"
    type: integer
    description: "Contagem de parágrafos"
    model: "local/python"
    compute: "feature-worker"

  has_image:
    version: "1.0"
    type: boolean
    description: "Artigo possui imagem"
    model: "local/python"
    compute: "feature-worker"

  has_video:
    version: "1.0"
    type: boolean
    description: "Artigo possui vídeo"
    model: "local/python"
    compute: "feature-worker"

  publication_hour:
    version: "1.0"
    type: integer
    description: "Hora de publicação (0-23 UTC)"
    model: "local/python"
    compute: "feature-worker"

  publication_dow:
    version: "1.0"
    type: integer
    description: "Dia da semana (0=seg, 6=dom)"
    model: "local/python"
    compute: "feature-worker"

  readability_flesch:
    version: "1.0"
    type: float
    description: "Flesch reading ease score (adaptado pt-BR)"
    model: "local/textstat"
    compute: "feature-worker"

  # --- Fase 1: Features IA (extensão do enrichment) ---
  sentiment:
    version: "1.0"
    type: object
    description: "Análise de sentimento {score: float, label: string}"
    model: "bedrock/claude-haiku"
    compute: "enrichment-worker"

  entities:
    version: "1.0"
    type: array
    description: "Entidades nomeadas [{text, type, count}]"
    model: "bedrock/claude-haiku"
    compute: "enrichment-worker"

  # --- Fase 3: Features analíticas ---
  trending_score:
    version: "1.0"
    type: float
    description: "Score de trending (volume + crescimento)"
    model: "bigquery/sql"
    compute: "airflow-dag"
```

### 0.5 — Criar bucket GCS via Terraform

**Repo**: `infra`
**Arquivo**: `terraform/gcs.tf` (novo)

```hcl
# =============================================================================
# DATA LAKE — GCS BUCKET
# =============================================================================

resource "google_storage_bucket" "data_lake" {
  name     = "${var.project_id}-dgb-data-lake"
  location = var.region
  project  = var.project_id

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true

  # Tiering automático: Standard → Nearline (90d) → Coldline (365d)
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 365
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  versioning {
    enabled = false  # Dados brutos são imutáveis, não precisam de versionamento
  }
}

# Permissão para o SA do scraper escrever no bucket (Bronze Writer futuro)
resource "google_storage_bucket_iam_member" "data_lake_scraper_writer" {
  bucket = google_storage_bucket.data_lake.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.scraper_api.email}"
}

# Permissão para o SA do GitHub Actions ler/escrever (DAGs de sync)
resource "google_storage_bucket_iam_member" "data_lake_github_actions" {
  bucket = google_storage_bucket.data_lake.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.github_actions.email}"
}

output "data_lake_bucket" {
  value       = google_storage_bucket.data_lake.name
  description = "Nome do bucket do Data Lake"
}
```

### 0.6 — Habilitar BigQuery API via Terraform

**Repo**: `infra`
**Arquivo**: `terraform/main.tf` (editar — adicionar junto aos outros `google_project_service`)

```hcl
resource "google_project_service" "bigquery" {
  project = var.project_id
  service = "bigquery.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}
```

### 0.7 — Testes da Fase 0

**Repo**: `data-platform`

| Arquivo de teste | O que testa |
|---|---|
| `tests/unit/test_news_features_schema.py` | Migration SQL é válida e idempotente |
| `tests/unit/test_postgres_manager_features.py` | Métodos upsert/get/get_batch com mocks |
| `tests/unit/test_feature_registry.py` | Feature Registry YAML é válido e completo |

### 0.8 — Verificação da Fase 0

```bash
# 1. Executar migration
psql "$DATABASE_URL" -f scripts/migrations/004_create_news_features.sql

# 2. Verificar tabela
psql "$DATABASE_URL" -c "\d news_features"

# 3. Testar insert + GIN index
psql "$DATABASE_URL" -c "
  INSERT INTO news_features (unique_id, features)
  SELECT unique_id, '{\"word_count\": 100}'::jsonb
  FROM news LIMIT 1;
"
psql "$DATABASE_URL" -c "
  SELECT unique_id, features->>'word_count' FROM news_features
  WHERE features @> '{\"word_count\": 100}';
"

# 4. Testar merge (||)
psql "$DATABASE_URL" -c "
  UPDATE news_features SET features = features || '{\"has_image\": true}'::jsonb
  WHERE unique_id = (SELECT unique_id FROM news_features LIMIT 1);
"

# 5. Terraform plan
cd infra/terraform && terraform plan -target=google_storage_bucket.data_lake -target=google_project_service.bigquery

# 6. Testes unitários
cd data-platform && poetry run pytest tests/unit/test_postgres_manager_features.py -v
```

### Entregáveis da Fase 0

| Repo | Arquivo | Ação |
|------|---------|------|
| `data-platform` | `scripts/migrations/004_create_news_features.sql` | Criar |
| `data-platform` | `src/data_platform/managers/postgres_manager.py` | Editar (+3 métodos) |
| `data-platform` | `src/data_platform/models/news.py` | Editar (+NewsFeatures) |
| `data-platform` | `feature_registry.yaml` | Criar |
| `data-platform` | `tests/unit/test_postgres_manager_features.py` | Criar |
| `data-platform` | `tests/unit/test_feature_registry.py` | Criar |
| `infra` | `terraform/gcs.tf` | Criar |
| `infra` | `terraform/main.tf` | Editar (+bigquery API) |

---

## Fase 1 — Feature Worker + Bronze Writer

**Objetivo**: Computar features locais (sem IA) e gravar dados brutos no Data Lake.
**Custo incremental**: +$1-2/mês
**Repos afetados**: `data-platform`, `infra`

### 1.1 — Feature Worker (Cloud Run, não Cloud Function)

Decisão: usar **Cloud Run** em vez de Cloud Function, seguindo o padrão já estabelecido nos outros workers (enrichment, typesense-sync, push-notifications). Isso mantém consistência de deploy, monitoring e Terraform.

**Repo**: `data-platform`
**Diretório**: `src/data_platform/workers/feature_worker/`

```
feature_worker/
├── __init__.py
├── app.py          # FastAPI endpoint /process (Pub/Sub push)
├── handler.py      # Lógica: fetch article → compute features → upsert
├── features.py     # Funções puras de computação de features
└── Dockerfile
```

#### `features.py` — Funções puras (testáveis)

```python
def compute_word_count(content: str | None) -> int
def compute_char_count(content: str | None) -> int
def compute_paragraph_count(content: str | None) -> int
def compute_has_image(image_url: str | None) -> bool
def compute_has_video(video_url: str | None) -> bool
def compute_publication_hour(published_at: datetime) -> int
def compute_publication_dow(published_at: datetime) -> int
def compute_readability_flesch(content: str | None) -> float | None

def compute_all(article: dict) -> dict:
    """Computa todas as features locais de um artigo.
    Retorna dict pronto para merge no JSONB."""
```

#### `handler.py` — Orquestração

```python
def handle_feature_computation(unique_id: str) -> None:
    """
    1. Fetch article from PostgreSQL (title, content, image_url, video_url, published_at)
    2. Compute all local features via features.compute_all()
    3. Upsert features via PostgresManager.upsert_features()
    4. (Fase futura) Publish to dgb.news.featured
    """
```

#### `app.py` — FastAPI (padrão dos outros workers)

```python
@app.post("/process")
async def process(request: Request) -> Response:
    """Pub/Sub push handler. ACK-always."""
    # Parse envelope → extract unique_id → handle_feature_computation(unique_id)
    # Idempotente: features são sobrescritas (upsert)
```

**Dependências** (`pyproject.toml` ou `requirements.txt`):
- `fastapi`, `uvicorn[standard]`, `psycopg2-binary`, `loguru`, `textstat`

**Testes**: `data-platform/tests/unit/test_feature_computation.py`
```python
# test_compute_word_count — texto normal
# test_compute_word_count_empty — conteúdo None/vazio
# test_compute_paragraph_count — contagem de \n\n
# test_compute_readability_flesch — texto em português
# test_compute_readability_flesch_empty — conteúdo None
# test_compute_has_image — com e sem URL
# test_compute_has_video — com e sem URL
# test_compute_publication_hour — timezone UTC
# test_compute_publication_dow — segunda=0, domingo=6
# test_compute_all — integração de todas as features
```

### 1.2 — Bronze Writer (Cloud Run)

**Repo**: `data-platform`
**Diretório**: `src/data_platform/workers/bronze_writer/`

```
bronze_writer/
├── __init__.py
├── app.py          # FastAPI endpoint /process
├── handler.py      # Fetch article → write JSON to GCS
├── storage.py      # GCS write logic
└── Dockerfile
```

#### `handler.py`

```python
def handle_bronze_write(unique_id: str, scraped_data: dict) -> None:
    """
    1. Fetch full article from PostgreSQL
    2. Serialize to JSON (include all raw fields)
    3. Write to GCS: gs://dgb-data-lake/bronze/news/YYYY/MM/DD/{unique_id}.json
    Path particionado por published_at do artigo.
    """
```

**Dependências**: `fastapi`, `uvicorn`, `psycopg2-binary`, `google-cloud-storage`, `loguru`

**Testes**: `data-platform/tests/unit/test_bronze_writer.py`
```python
# test_gcs_path_generation — verifica particionamento por data
# test_json_serialization — verifica que todos os campos são incluídos
# test_idempotency — mesmo artigo reescrito sem erro
```

### 1.3 — Terraform para Feature Worker + Bronze Writer

**Repo**: `infra`
**Arquivos**: `terraform/feature-worker.tf`, `terraform/bronze-writer.tf` (novos)

Cada um segue o padrão de `enrichment-worker.tf`:
- Service Account dedicado
- Cloud Run v2 service (min=0, max=2)
- Secret access (DATABASE_URL)
- Feature Worker: subscriber de `dgb.news.enriched`
- Bronze Writer: subscriber de `dgb.news.scraped`

**Pub/Sub** (`terraform/pubsub.tf` — editar):
- Nova subscription: `dgb.news.enriched--features` → feature-worker `/process`
- Nova subscription: `dgb.news.scraped--bronze` → bronze-writer `/process`
- Novo topic: `dgb.news.featured` (retention 7d)
- DLQs correspondentes

### 1.4 — Estender Enrichment Worker (sentiment + entities)

**Repo**: `data-science`
**Arquivo**: `src/news_enrichment/worker/handler.py` (editar)

Após classificação temática + summary (que já é feita), adicionar ao prompt:
- Sentiment: `{"score": -1.0 a 1.0, "label": "negative"|"neutral"|"positive"}`
- Entities: `[{"text": "MEC", "type": "ORG|PER|LOC|MISC", "count": 3}]`

O enrich_article já chama Bedrock — o custo marginal de pedir sentiment e entities no mesmo prompt é zero (tokens de output são baratos comparados ao input que já é enviado).

Após receber resultado do LLM, chamar `PostgresManager.upsert_features()` com:
```python
features = {
    "sentiment": result.get("sentiment"),
    "entities": result.get("entities"),
}
postgres_manager.upsert_features(unique_id, features)
```

**Testes**: `data-science/tests/test_enrichment_features.py`
```python
# test_sentiment_extraction — mock Bedrock response com sentiment
# test_entities_extraction — mock Bedrock response com entities
# test_features_upserted — verifica que upsert_features é chamado
# test_enrichment_without_features — fallback quando LLM não retorna
```

### 1.5 — GitHub Actions Workflows

**Feature Worker**: `.github/workflows/deploy-feature-worker.yaml`
**Bronze Writer**: `.github/workflows/deploy-bronze-writer.yaml`

Ambos usam `destaquesgovbr/reusable-workflows/.github/workflows/cloud-run-deploy.yml@v2`.

### Entregáveis da Fase 1

| Repo | Arquivo | Ação |
|------|---------|------|
| `data-platform` | `src/data_platform/workers/feature_worker/` | Criar (4 arquivos) |
| `data-platform` | `src/data_platform/workers/bronze_writer/` | Criar (4 arquivos) |
| `data-platform` | `tests/unit/test_feature_computation.py` | Criar |
| `data-platform` | `tests/unit/test_bronze_writer.py` | Criar |
| `data-science` | `src/news_enrichment/worker/handler.py` | Editar |
| `data-science` | `tests/test_enrichment_features.py` | Criar |
| `infra` | `terraform/feature-worker.tf` | Criar |
| `infra` | `terraform/bronze-writer.tf` | Criar |
| `infra` | `terraform/pubsub.tf` | Editar (+2 subs, +1 topic, +DLQs) |

---

## Fase 2 — BigQuery Analytics

**Objetivo**: Camada Gold para analytics sem sobrecarregar o PostgreSQL.
**Custo incremental**: +$0-5/mês (free tier: 1TB queries, 10GB storage)
**Repos afetados**: `data-platform`, `infra`

### 2.1 — BigQuery Dataset e Tabelas via Terraform

**Repo**: `infra`
**Arquivo**: `terraform/bigquery.tf` (novo)

```hcl
resource "google_bigquery_dataset" "dgb_gold" {
  dataset_id = "dgb_gold"
  location   = "US"  # Free tier disponível apenas em US multi-region
  project    = var.project_id

  default_table_expiration_ms = null  # Sem expiração
  delete_contents_on_destroy  = false

  labels = {
    environment = "production"
    layer       = "gold"
  }
}
```

Tabelas criadas via SQL (não Terraform, para flexibilidade):

**`fato_noticias`** — Particionada por `published_at`:
```sql
CREATE TABLE dgb_gold.fato_noticias (
  unique_id STRING NOT NULL,
  title STRING,
  agency_key STRING,
  agency_name STRING,
  theme_l1_code STRING,
  theme_l1_label STRING,
  theme_l2_code STRING,
  theme_l2_label STRING,
  most_specific_theme_code STRING,
  most_specific_theme_label STRING,
  published_at TIMESTAMP NOT NULL,
  word_count INT64,
  has_image BOOL,
  has_video BOOL,
  sentiment_score FLOAT64,
  sentiment_label STRING,
  publication_hour INT64,
  publication_dow INT64,
  readability_flesch FLOAT64
)
PARTITION BY DATE(published_at)
CLUSTER BY agency_key, theme_l1_code;
```

**`dim_agencias`** e **`dim_temas`**: tabelas de dimensão simples.

### 2.2 — DAG Airflow: PG → BigQuery (incremental diário)

**Repo**: `data-platform`
**Arquivo**: `src/data_platform/dags/sync_pg_to_bigquery.py`

```python
# Schedule: diário às 7 AM UTC (após HuggingFace sync às 6 AM)
# Lógica:
# 1. Query PG: SELECT news + JOIN news_features WHERE published_at >= yesterday
# 2. Export para Parquet em GCS silver/analytics/YYYY-MM-DD.parquet
# 3. BigQuery LOAD JOB do Parquet (append)
# 4. Log no sync_log
```

**Testes**: `data-platform/tests/unit/test_dag_bigquery_sync.py`
```python
# test_dag_structure — DAG válida, schedule correto, task dependencies
# test_query_incremental — verifica que a query filtra por data
# test_parquet_schema — verifica colunas do Parquet exportado
```

### 2.3 — External Tables sobre Bronze

```sql
-- Tabela externa sobre dados brutos no GCS
CREATE EXTERNAL TABLE dgb_gold.raw_news_bronze
OPTIONS (
  format = 'JSON',
  uris = ['gs://inspire-7-finep-dgb-data-lake/bronze/news/*/*.json']
);
```

### Entregáveis da Fase 2

| Repo | Arquivo | Ação |
|------|---------|------|
| `infra` | `terraform/bigquery.tf` | Criar |
| `data-platform` | `scripts/bigquery/create_tables.sql` | Criar |
| `data-platform` | `src/data_platform/dags/sync_pg_to_bigquery.py` | Criar |
| `data-platform` | `src/data_platform/jobs/bigquery/` | Criar (módulo) |
| `data-platform` | `tests/unit/test_dag_bigquery_sync.py` | Criar |

---

## Fase 3 — Features Avançadas

**Objetivo**: Trending, clusters, engajamento.
**Custo incremental**: +$2-5/mês
**Repos afetados**: `data-platform`, `portal`, `infra`

### 3.1 — Trending Score

**DAG Airflow** (a cada 6h):
1. Query BigQuery: artigos por tema nas últimas 24h, calcular taxa de crescimento vs média 7d
2. Resultado: lista de `(unique_id, trending_score)`
3. Batch UPDATE em `news_features` via `upsert_features`
4. Pub/Sub `dgb.news.featured` para Typesense sync

**Testes**:
```python
# test_trending_query — verifica SQL de cálculo de trending
# test_trending_batch_upsert — verifica update em lote
```

### 3.2 — Topic Clusters (artigos similares)

**Job batch** (DAG diário):
1. Query pgvector: para cada artigo das últimas 24h, buscar 5 mais similares (cosine similarity > 0.8)
2. Resultado: `similar_articles: ["id1", "id2", ...]`
3. Upsert em `news_features`

**Testes**:
```python
# test_similarity_query — verifica que usa cosine e threshold
# test_cluster_assignment — verifica formato do resultado
```

### 3.3 — Métricas de Engajamento

**Portal** (`portal/src/lib/analytics.ts`):
- Enviar pageview events para endpoint analytics
- Campos: `unique_id`, `timestamp`, `session_id`, `referrer`

**Infra**:
- Novo topic Pub/Sub: `dgb.portal.pageview`
- Cloud Run worker ou Cloud Function: subscriber → INSERT no BigQuery

**DAG**: Agregar views/article diariamente → `news_features.view_count`

### 3.4 — Typesense Feature Sync

**Editar** Typesense collection para suportar novos campos:

```python
# Novos campos em collection.py (todos optional):
{"name": "sentiment_label", "type": "string", "facet": True, "optional": True},
{"name": "sentiment_score", "type": "float", "facet": False, "optional": True},
{"name": "trending_score", "type": "float", "facet": False, "optional": True, "sort": True},
{"name": "word_count", "type": "int32", "facet": False, "optional": True},
```

O Typesense Sync Worker existente é estendido para incluir features do `news_features` JOIN.

### Entregáveis da Fase 3

| Repo | Arquivo | Ação |
|------|---------|------|
| `data-platform` | `src/data_platform/dags/compute_trending.py` | Criar |
| `data-platform` | `src/data_platform/jobs/bigquery/trending.py` | Criar |
| `data-platform` | `src/data_platform/jobs/similarity/clusters.py` | Criar |
| `data-platform` | `src/data_platform/typesense/collection.py` | Editar (+campos) |
| `data-platform` | `src/data_platform/typesense/indexer.py` | Editar (JOIN features) |
| `portal` | `src/lib/analytics.ts` | Criar |
| `infra` | `terraform/pubsub.tf` | Editar (+pageview topic) |
| `infra` | `terraform/bigquery.tf` | Editar (+tabela pageviews) |

---

## Fase 4 — Dados de Usuário (Firestore)

**Objetivo**: Personalização e preferências persistentes cross-device.
**Custo incremental**: +$0-2/mês (free tier)
**Repos afetados**: `portal`, `infra`

### 4.1 — Provisionar Firestore via Terraform

```hcl
resource "google_firestore_database" "main" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
}
```

### 4.2 — Collections

```
users/{uid}/
  profile: { display_name, email, role }
  preferences: {
    push_filters: [{type, value}],
    notification_frequency: "instant" | "daily" | "weekly",
    theme_subscriptions: ["Educação", "Saúde"]
  }

reading_history/{uid}/articles/{unique_id}/
  read_at: timestamp
  time_spent_seconds: number
  source: "push" | "feed" | "search"
```

### 4.3 — Portal Integration

- Firebase SDK no Next.js (client-side)
- Auth via Firebase Authentication (Google Sign-In)
- Preferências salvas no Firestore (substituem localStorage)
- Histórico de leitura para recomendações futuras

### Entregáveis da Fase 4

| Repo | Arquivo | Ação |
|------|---------|------|
| `infra` | `terraform/firestore.tf` | Criar |
| `portal` | `src/lib/firebase.ts` | Criar |
| `portal` | `src/components/auth/` | Criar |
| `portal` | `src/hooks/usePreferences.ts` | Criar |
| `portal` | `src/hooks/useReadingHistory.ts` | Criar |

---

## Resumo de Custos

| Componente | Fase | Custo/mês |
|-----------|------|-----------|
| GCS bucket (~20GB com tiering) | 0 | ~$0.40 |
| Cloud Run Feature Worker | 1 | ~$0.50 |
| Cloud Run Bronze Writer | 1 | ~$0.50 |
| Pub/Sub (novos topics) | 1 | ~$0.05 |
| BigQuery (free tier) | 2 | $0 |
| Firestore (free tier) | 4 | $0 |
| **Total (fases 0-4)** | | **~$1.50-4/mês** |

---

## Resumo de Testes por Fase

| Fase | Arquivo de teste | # testes (est.) |
|------|-----------------|-----------------|
| 0 | `test_postgres_manager_features.py` | 7 |
| 0 | `test_feature_registry.py` | 3 |
| 1 | `test_feature_computation.py` | 10 |
| 1 | `test_bronze_writer.py` | 3 |
| 1 | `test_enrichment_features.py` | 4 |
| 2 | `test_dag_bigquery_sync.py` | 3 |
| 3 | `test_trending.py` | 2 |
| 3 | `test_similarity_clusters.py` | 2 |
| **Total** | | **~34 testes** |

---

## O que NÃO fazer

| Tentação | Motivo |
|----------|--------|
| MongoDB/Firestore como substituto do PG | JSONB cobre 95% dos casos para 300k registros |
| Vertex AI Feature Store | Over-engineering para o volume atual |
| Migrar embeddings para fora do PG | pgvector funciona; busca semântica via Typesense |
| Kafka/Flink | Pub/Sub já cumpre event streaming |
| API separada para features | Typesense serve o portal; features vão para lá |
| Cloud Functions (em vez de Cloud Run) | Inconsistente com os outros workers |
