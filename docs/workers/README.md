# Cloud Run Workers

Workers são serviços Cloud Run event-driven que processam mensagens Pub/Sub em tempo real.

---

## Visão Geral

| Worker | Topic | Output | Deploy |
|--------|-------|--------|--------|
| bronze-writer | `dgb.news.scraped` | GCS raw JSON | `bronze-writer-deploy.yaml` |
| feature-worker | `dgb.news.enriched` | `news_features` table | `feature-worker-deploy.yaml` |
| thumbnail-worker | `dgb.news.enriched` | GCS thumbnails | `thumbnail-worker-deploy.yaml` |
| typesense-sync | `dgb.news.enriched` + `dgb.news.embedded` | Typesense index | `typesense-sync-worker-deploy.yaml` |

---

## Arquitetura

```
Pub/Sub Topics
    │
    ├── dgb.news.scraped ──────→ Bronze Writer ──→ GCS (bronze/)
    │
    ├── dgb.news.enriched ─────→ Feature Worker ──→ PostgreSQL (news_features)
    │                      ├───→ Thumbnail Worker ──→ GCS (thumbnails/)
    │                      └───→ Typesense Sync ──→ Typesense
    │
    └── dgb.news.embedded ─────→ Typesense Sync ──→ Typesense (update embedding)
```

---

## Detalhes por Worker

### bronze-writer

Persiste dados raw do scraper na camada Bronze (GCS) como audit trail imutável.

- **Topic**: `dgb.news.scraped`
- **Output**: `gs://{GCS_BUCKET}/bronze/news/YYYY/MM/DD/{unique_id}.json`
- **Código**: `src/data_platform/workers/bronze_writer/` (app.py, handler.py, storage.py)
- **Docker**: `docker/bronze-writer/Dockerfile`
- **Env vars extras**: `GCS_BUCKET`, `GCP_PROJECT_ID`

### feature-worker

Computa features locais para artigos enriquecidos. Features definidas em `feature_registry.yaml`.

- **Topic**: `dgb.news.enriched`
- **Output**: tabela `news_features` (JSONB) — word_count, read_time, readability, etc.
- **Código**: `src/data_platform/workers/feature_worker/` (app.py, handler.py, features.py)
- **Docker**: `docker/feature-worker/Dockerfile`

### thumbnail-worker

Gera thumbnails para notícias de vídeo sem imagem, extraindo frame via ffmpeg.

- **Topic**: `dgb.news.enriched`
- **Output**: thumbnails em GCS + atualiza `news.image_url`
- **Código**: `src/data_platform/workers/thumbnail_worker/` (app.py, handler.py, extractor.py, storage.py)
- **Docker**: `docker/thumbnail-worker/Dockerfile`
- **Env vars extras**: `GCS_BUCKET`, `GCP_PROJECT_ID`
- **DAG complementar**: `generate_video_thumbnails` faz backfill batch a cada 4h

### typesense-sync

Mantém o índice Typesense sincronizado em tempo real.

- **Topics**: `dgb.news.enriched` (indexa conteúdo) + `dgb.news.embedded` (atualiza vetor)
- **Output**: upsert na collection `news` do Typesense
- **Código**: `src/data_platform/workers/typesense_sync/` (app.py, handler.py)
- **Docker**: `docker/typesense-sync-worker/Dockerfile`
- **Env vars extras**: `TYPESENSE_HOST`, `TYPESENSE_PORT`, `TYPESENSE_API_KEY`
- **Workflows de manutenção**: `typesense-maintenance-sync.yaml` (batch), `typesense-schema-update.yaml`

---

## Padrão Comum

### Endpoints

| Método | Path | Função |
|--------|------|--------|
| GET | `/health` | Health check (Cloud Run liveness) |
| POST | `/process` | Recebe Pub/Sub push message |

### Fluxo de Processamento

1. Pub/Sub envia POST para `/process` com message base64-encoded
2. Worker decodifica e extrai `unique_id` do artigo
3. Busca artigo completo no PostgreSQL via `PostgresManager`
4. Processa (específico de cada worker)
5. Retorna 200 (ack) ou 4xx/5xx (nack → Pub/Sub retry)

### Estrutura de Código

```
src/data_platform/workers/<worker_name>/
├── app.py          # FastAPI app, endpoints, Pub/Sub message parsing
├── handler.py      # Business logic (testável isoladamente)
└── ...             # Módulos específicos (storage.py, features.py, etc.)
```

### Lazy Initialization

Workers inicializam `PostgresManager` de forma lazy (no primeiro request) para evitar problemas com cold starts do Cloud Run:

```python
_pg: PostgresManager | None = None

def _get_pg() -> PostgresManager:
    global _pg
    if _pg is None:
        _pg = PostgresManager()
    return _pg
```

---

## Deploy

Cada worker tem seu próprio workflow em `.github/workflows/`:
- Triggered por push to main (quando arquivos relevantes mudam)
- Build da imagem Docker
- Push para Artifact Registry
- Deploy para Cloud Run

---

## Variáveis de Ambiente

Workers herdam configuração de `src/data_platform/config.py` (pydantic-settings). As principais:

- `DATABASE_URL` — PostgreSQL connection string (todos)
- `GCP_PROJECT_ID` — Projeto GCP (bronze-writer, thumbnail-worker)
- `GCS_BUCKET` — Bucket GCS (bronze-writer, thumbnail-worker)
- `TYPESENSE_HOST`, `TYPESENSE_API_KEY` — Typesense (typesense-sync)

---

## Adicionando um Novo Worker

1. Criar diretório `src/data_platform/workers/<name>/` com `app.py` e `handler.py`
2. Criar `docker/<name>/Dockerfile`
3. Criar `.github/workflows/<name>-deploy.yaml`
4. Configurar Pub/Sub subscription (push) no Terraform (repo infra)
