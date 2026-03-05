# Plano: Serviço de Verificação de Integridade de Notícias (data-platform#68)

## Contexto

Notícias raspadas de ~155 sites gov.br armazenam apenas **URLs de imagem** (não fazem download). Quando a fonte edita a notícia e a imagem muda ou é removida, o portal exibe imagem quebrada sem tratamento. Precisamos verificar periodicamente a integridade dessas URLs e marcar artigos problemáticos.

## Arquitetura

Segue o padrão existente: **DAG orquestra, Cloud Run executa**.

```
DAG verify_news_integrity (data-platform, a cada 30 min)
  │
  ├─ Task 1: fetch_priority_batch
  │   └─ Query PostgreSQL → lista de unique_ids + urls para verificar
  │
  ├─ Task 2: call_scraper_verify
  │   └─ POST /verify/integrity no Scraper Cloud Run
  │       └─ Scraper faz HTTP HEAD nas imagens + GET condicional no conteúdo
  │       └─ Retorna resultados por artigo
  │
  ├─ Task 3: upsert_results
  │   └─ Upsert resultados em news_features.features.integrity
  │
  └─ Task 4: sync_integrity_to_typesense
      └─ Atualiza campo image_broken nos docs Typesense afetados
```

### Por que no Scraper Cloud Run?

- Já tem toda a infra de HTTP requests para gov.br (headers, anti-bot detection, timeouts)
- Segue o padrão: DAGs não fazem HTTP para sites externos, delegam para Cloud Run
- Reutiliza `WebScraper.fetch_page()` e `_extract_image_url()` para re-verificação de conteúdo
- Mesmo deploy pipeline (push to main → Cloud Run auto-deploy)

---

## Repo: scraper — Novo endpoint `POST /verify/integrity`

### Arquivos a criar

#### `src/govbr_scraper/integrity/__init__.py`
Package init.

#### `src/govbr_scraper/integrity/checker.py`
Funções de verificação:

```python
def check_image(image_url: str, timeout=10) -> dict:
    """HTTP HEAD na URL da imagem. Retorna status/http_code/content_type."""
    # requests.head(image_url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    # Retorna: {"image_status": "ok|broken|timeout", "image_http_code": 200, ...}

def check_content(source_url: str, stored_hash: str|None, stored_etag: str|None, timeout=15) -> dict:
    """GET condicional (If-None-Match) na URL fonte. Compara hash SHA-256."""
    # Se 304 → unchanged
    # Se 404 → removed
    # Se hash diferente → changed (extrai nova image_url também)
    # Retorna: {"content_status": "unchanged|changed|removed", "content_hash": "sha256:...", "new_image_url": ...}
```

- Usa `requests` (já é dependência, mesmo lib do webscraper)
- Reutiliza `DEFAULT_HEADERS` do webscraper para parecer browser real
- `check_content` também re-extrai `image_url` da página para detectar mudança de imagem

#### `src/govbr_scraper/integrity/service.py`
Orquestrador que processa um batch:

```python
def verify_batch(articles: list[dict]) -> dict:
    """Verifica integridade de um batch de artigos.

    Input: [{"unique_id": "...", "url": "...", "image_url": "...", "content_hash": "...", "source_etag": "..."}]
    Output: {"results": [...], "summary": {"total": N, "images_ok": N, "images_broken": N, ...}}
    """
    # Para cada artigo:
    #   1. check_image(image_url) se image_url existe
    #   2. check_content(url, stored_hash, etag) para subset (flag check_content=true)
    # Usa ThreadPoolExecutor(max_workers=20) para paralelismo
```

### Arquivos a modificar

#### `src/govbr_scraper/api.py`
Adicionar endpoint + models:

```python
class VerifyRequest(BaseModel):
    articles: list[VerifyArticle]  # unique_id, url, image_url, content_hash, source_etag, check_content

class VerifyArticle(BaseModel):
    unique_id: str
    url: str | None = None
    image_url: str | None = None
    content_hash: str | None = None
    source_etag: str | None = None
    check_content: bool = False

@app.post("/verify/integrity")
def verify_integrity(req: VerifyRequest):
    from govbr_scraper.integrity.service import verify_batch
    return verify_batch(req.articles)
```

#### `tests/unit/test_integrity.py` (novo)
Testes unitários para checker.py com mocks de requests.

---

## Repo: data-platform — DAG + processamento de resultados

### Arquivos a criar

#### `src/data_platform/jobs/integrity/__init__.py`
Package init.

#### `src/data_platform/jobs/integrity/priority.py`
Query SQL de priorização:

```python
def fetch_priority_batch(db_url: str, batch_size=400) -> list[dict]:
    """Busca artigos priorizados para verificação."""
```

Tiers de prioridade (filtra artigos já verificados recentemente):

| Tier | Idade | Intervalo re-check | Batch/run |
|------|-------|--------------------|-----------|
| 1 | < 3h | 10 min | ~200 |
| 2 | 3h-24h | 1h | ~100 |
| 3 | 1-7 dias | 6h | ~50 |
| 4 | 7-30 dias | 24h | ~30 |
| 5 | 1-5 meses | 7 dias | ~20 |

Query ordena por: tier → nunca verificados primeiro → check mais antigo.
Artigos > 5 meses excluídos.

#### `src/data_platform/jobs/integrity/results.py`
Processamento de resultados retornados pelo scraper:

```python
def upsert_integrity_results(db_url: str, results: list[dict]) -> int:
    """Upsert resultados no news_features.features.integrity via JSONB || merge."""

def sync_image_status_to_typesense(typesense_config: dict, broken_ids: list, fixed_ids: list):
    """Atualiza campo image_broken nos documentos Typesense."""
```

#### `src/data_platform/dags/verify_news_integrity.py`
DAG seguindo padrão `compute_trending.py`:

```python
@dag(
    dag_id="verify_news_integrity",
    schedule="*/30 * * * *",  # A cada 30 min
    max_active_runs=1,
    tags=["silver", "integrity", "quality"],
    default_args={"execution_timeout": timedelta(minutes=25), "retries": 1},
)
def verify_news_integrity_dag():

    @task()
    def fetch_batch(**ctx):
        # Query PG com priorização → lista de artigos
        # Marca quais devem ter check_content=True (subset menor, ~50)
        return articles

    @task()
    def call_scraper(articles):
        # POST /verify/integrity no Cloud Run do scraper
        # Usa Variable.get("scraper_api_url")
        return response_json

    @task()
    def save_results(results):
        # Upsert em news_features.features.integrity
        # Retorna listas de broken_ids e fixed_ids
        return {"broken_ids": [...], "fixed_ids": [...]}

    @task()
    def sync_typesense(changes):
        # Atualiza image_broken no Typesense
        pass

    batch = fetch_batch()
    results = call_scraper(batch)
    changes = save_results(results)
    sync_typesense(changes)
```

#### `tests/unit/test_integrity_priority.py` (novo)
Testes para lógica de priorização.

### Arquivos a modificar

#### `src/data_platform/typesense/collection.py`
Adicionar ao `COLLECTION_SCHEMA["fields"]`:
```python
{"name": "image_broken", "type": "bool", "facet": True, "optional": True},
```

---

## Estrutura de Features (news_features JSONB)

```json
{
  "integrity": {
    "image_status": "ok|broken|redirect|timeout|no_image",
    "image_http_code": 200,
    "image_checked_at": "2026-03-04T12:00:00Z",
    "content_status": "unchanged|changed|removed|error|unchecked",
    "content_hash": "sha256:abc123...",
    "content_checked_at": "2026-03-04T12:00:00Z",
    "source_etag": "\"xyz789\"",
    "check_count": 5
  }
}
```

---

## Sequência de Implementação

### PR 1 — scraper: endpoint `/verify/integrity`
1. Criar `integrity/checker.py` (check_image, check_content)
2. Criar `integrity/service.py` (verify_batch com ThreadPool)
3. Adicionar endpoint em `api.py`
4. Testes unitários

### PR 2 — data-platform: DAG + processamento
1. Criar `jobs/integrity/priority.py`
2. Criar `jobs/integrity/results.py`
3. Criar `dags/verify_news_integrity.py`
4. Adicionar `image_broken` ao schema Typesense
5. Testes unitários

---

## Padrões Reutilizados

| Padrão | Origem | Uso |
|--------|--------|-----|
| DAG `@dag/@task` + `BaseHook.get_connection` | `compute_trending.py` | Estrutura da DAG |
| `requests.get/head` + `DEFAULT_HEADERS` | `webscraper.py:132` | HTTP requests no checker |
| SQLAlchemy + NullPool + `engine.begin()` | `trending.py:batch_upsert_trending` | Upsert batch |
| JSONB `||` merge | `postgres_manager.py:upsert_features` | Merge não-destrutivo |
| `ScrapeRequest/Response` Pydantic models | `api.py` | Models do endpoint verify |
| `COLLECTION_SCHEMA` fields | `collection.py` | Campo `image_broken` |

## Verificação

1. **scraper**: `poetry run pytest tests/unit/test_integrity.py -v`
2. **scraper local**: `poetry run uvicorn govbr_scraper.api:app --reload` → `curl -X POST localhost:8000/verify/integrity -d '{"articles": [...]}'`
3. **data-platform**: `poetry run pytest tests/unit/test_integrity_priority.py -v`
4. **DAG parse**: `python -c "from data_platform.dags.verify_news_integrity import dag_instance; print(dag_instance)"`

## Fora de Escopo (futuro)

- Fallback de imagem no portal (PR separado, repo portal)
- Re-scraping automático de artigos com conteúdo alterado
- Dashboard de métricas de integridade no BigQuery
