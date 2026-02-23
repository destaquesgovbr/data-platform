# Plano: Scraper API no Cloud Run + DAGs Leves no Airflow

## Contexto

As DAGs de scraping (`scrape_agencies.py`, `scrape_ebc.py`) executam o código do scraper diretamente nos workers do Airflow. Isso exige instalar todas as dependências (beautifulsoup4, requests, retry, markdownify, pydantic, etc.) no Composer e sincronizar o source code para `plugins/`. Cada update de dependências leva 10-20 min e coloca o Composer em estado UPDATING.

**Objetivo**: Mover a execução do scraper para um serviço Cloud Run com API HTTP. As DAGs do Airflow passam a fazer apenas chamadas HTTP — leves, sem dependências extras.

## Arquitetura

```
Airflow DAG (leve)              Cloud Run (scraper-api)
┌─────────────────┐   HTTP POST   ┌─────────────────────┐
│ scrape_mec      │──────────────→│ POST /scrape/agencies│
│ (httpx + auth)  │   Bearer IAM  │ ScrapeManager.run()  │
└─────────────────┘               │ → PostgreSQL         │
                                  └─────────────────────┘
```

## Arquivos a Criar/Modificar

### Novos
| Arquivo | Propósito |
|---------|-----------|
| `src/data_platform/api.py` | FastAPI app com endpoints `/scrape/agencies`, `/scrape/ebc`, `/health` |

### Modificados
| Arquivo | Mudança |
|---------|---------|
| `pyproject.toml` | Adicionar `fastapi` e `uvicorn` |
| `src/data_platform/dags/scrape_agencies.py` | Reescrever: chamada HTTP ao Cloud Run em vez de imports diretos |
| `src/data_platform/dags/scrape_ebc.py` | Idem |
| `src/data_platform/dags/requirements.txt` | Trocar deps do scraper por `httpx` + `google-auth` |
| `.github/workflows/postgres-docker-build.yaml` | Adicionar job de deploy ao Cloud Run após build da imagem |

### Removíveis após migração
| Arquivo | Motivo |
|---------|--------|
| `src/data_platform/dags/config/site_urls.yaml` | Não é mais necessário nas DAGs (Cloud Run carrega do próprio source) |
| Step "Deploy data_platform source to plugins/" no workflow | DAGs não importam mais `data_platform` |

## Implementação

### Passo 1: Adicionar FastAPI ao pyproject.toml

```toml
# Em [tool.poetry.dependencies]
fastapi = "^0.115.0"
uvicorn = {version = "^0.34.0", extras = ["standard"]}
```

### Passo 2: Criar `src/data_platform/api.py`

Endpoints:
- `POST /scrape/agencies` — recebe `{start_date, end_date, agencies[], allow_update, sequential}`
- `POST /scrape/ebc` — recebe `{start_date, end_date, allow_update, sequential}`
- `GET /health` — health check

Internamente chama `ScrapeManager.run_scraper()` e `EBCScrapeManager.run_scraper()` (mesmos que o CLI usa). Imports lazy dentro dos endpoints. `StorageAdapter()` lê `DATABASE_URL` e `STORAGE_BACKEND` do ambiente — zero mudanças no código existente.

### Passo 3: Estender workflow de build com deploy ao Cloud Run

Adicionar job `deploy-scraper-api` ao `postgres-docker-build.yaml`:

```yaml
deploy-scraper-api:
  needs: build-and-push
  steps:
    - Authenticate to GCP (Workload Identity)
    - gcloud run deploy destaquesgovbr-scraper-api \
        --image ghcr.io/destaquesgovbr/data-platform:$SHA \
        --region southamerica-east1 \
        --no-allow-unauthenticated \
        --set-secrets "DATABASE_URL=govbrnews-postgres-connection-string:latest" \
        --set-env-vars "STORAGE_BACKEND=postgres" \
        --command uvicorn --args "data_platform.api:app,--host,0.0.0.0,--port,8080" \
        --timeout 900 --concurrency 1 \
        --min-instances 0 --max-instances 10 \
        --memory 1Gi --cpu 1
```

Config chave:
- `--concurrency 1`: um scrape por container (CPU/IO intensivo)
- `--timeout 900`: 15 min (matching Airflow execution_timeout)
- `--min-instances 0`: scale-to-zero quando idle
- `--no-allow-unauthenticated`: IAM auth obrigatória

### Passo 4: Reescrever DAGs para chamadas HTTP

**scrape_agencies.py** — a task passa a ser:
```python
@task
def scrape(logical_date=None):
    import google.auth.transport.requests
    import google.oauth2.id_token
    import httpx

    url = os.environ.get("SCRAPER_API_URL")
    auth_req = google.auth.transport.requests.Request()
    token = google.oauth2.id_token.fetch_id_token(auth_req, url)

    min_date = (logical_date - timedelta(hours=1)).strftime("%Y-%m-%d")
    max_date = logical_date.strftime("%Y-%m-%d")

    response = httpx.post(
        f"{url}/scrape/agencies",
        json={"start_date": min_date, "end_date": max_date, "agencies": [agency_key]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=900.0,
    )
    response.raise_for_status()
```

**scrape_ebc.py** — mesmo padrão, chamando `/scrape/ebc`.

### Passo 5: Simplificar requirements.txt das DAGs

Remover dependências do scraper, manter apenas:
```
huggingface-hub==0.27.0
pyarrow>=14.0.0
requests>=2.31.0
httpx>=0.27.0
google-auth>=2.29.0
```

### Passo 6: IAM — dar permissão ao Composer

```bash
gcloud run services add-iam-policy-binding destaquesgovbr-scraper-api \
  --region=southamerica-east1 \
  --member="serviceAccount:<COMPOSER_SA>@inspire-7-finep.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

### Passo 7: Configurar Airflow Variable

Setar `SCRAPER_API_URL` como variável de ambiente no Composer:
```bash
gcloud composer environments update destaquesgovbr-composer \
  --location=us-central1 \
  --update-env-variables=SCRAPER_API_URL=https://destaquesgovbr-scraper-api-HASH.southamerica-east1.run.app
```

## Estratégia de Migração Incremental

1. **Fase A**: Deploy da API (sem mudar DAGs) → testar endpoints com `curl`
2. **Fase B**: Criar DAG de teste HTTP com 3-5 agências → rodar em paralelo com DAGs atuais por 2-3 dias
3. **Fase C**: Substituir DAGs → remover deps do scraper do Composer
4. **Fase D**: Cleanup → remover step plugins/ do workflow, remover `dags/config/`

## Verificação

1. `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://SCRAPER_API_URL/health`
2. Trigger manual de DAG no Airflow UI → verificar logs com response 200
3. Query PostgreSQL: `SELECT agency_key, COUNT(*) FROM news WHERE created_at > NOW() - INTERVAL '1 hour' GROUP BY agency_key`
