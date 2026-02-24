# Plano: Migrar Scraper para Airflow com DAG por Órgão

## Contexto

Issue: `data-platform#57`

O scraping de ~158 agências gov.br roda via GitHub Actions (`main-workflow.yaml`) de forma sequencial, 1x/dia. Isso causa execução lenta, falhas em cascata e monitoramento limitado. A migração para Airflow com uma DAG por órgão traz resiliência (falha isolada), paralelismo, monitoramento granular e frequência de 15 minutos.

## Decisões

| Decisão | Escolha |
|---------|---------|
| Disponibilização do código | Instalar `data-platform` como pacote pip no Composer |
| Estrutura de DAGs | ~158 DAGs individuais, geradas dinamicamente |
| Schedule | A cada 15 minutos (`*/15 * * * *`) |
| Config source | `site_urls.yaml` existente (carregado no parse da DAG) |
| Storage bridge | Env var `DATABASE_URL` extraída do `PostgresHook` |

## Arquivos a Criar/Modificar

### Novos
| Arquivo | Propósito |
|---------|-----------|
| `src/data_platform/dags/scrape_agencies.py` | Gerador dinâmico de ~158 DAGs de scraping |
| `src/data_platform/dags/scrape_ebc.py` | DAG para scraping EBC (Agência Brasil, TV Brasil) |
| `src/data_platform/dags/config/site_urls.yaml` | Cópia do config de URLs (acessível pelas DAGs no GCS) |

### Modificados
| Arquivo | Mudança |
|---------|---------|
| `.github/workflows/composer-deploy-dags.yaml` | Incluir deploy da pasta `config/` junto com as DAGs |
| `src/data_platform/dags/requirements.txt` | Adicionar dependências do scraper (ou instalar `data-platform` via git) |

### Sem alteração (reutilizados as-is)
- `scrapers/webscraper.py`, `scrapers/scrape_manager.py`
- `managers/storage_adapter.py`, `managers/postgres_manager.py`
- `models/news.py`

## Implementação

### Passo 1: Preparar requirements.txt para o Composer

Criar/atualizar `src/data_platform/dags/requirements.txt` com o pacote data-platform instalável via git:

```
data-platform @ git+https://github.com/destaquesgovbr/data-platform.git
```

Alternativa se o repo for privado: publicar wheel no GCS e referenciar.

O workflow `composer-deploy-dags.yaml` já faz deploy de `requirements.txt` automaticamente (linhas 126-136).

### Passo 2: Copiar site_urls.yaml para pasta de DAGs

Copiar `src/data_platform/scrapers/config/site_urls.yaml` para `src/data_platform/dags/config/site_urls.yaml`.

Isso garante que o arquivo esteja disponível no GCS bucket do Composer junto com as DAGs.

### Passo 3: Criar DAG geradora (`scrape_agencies.py`)

Estrutura do arquivo:

```python
"""
Gera ~158 DAGs de scraping, uma por agência gov.br.

Cada DAG:
- Roda a cada 15 minutos
- Scrape notícias da última hora (janela de segurança)
- Insere no PostgreSQL via StorageAdapter
- Retry: 2x com backoff de 5 min
- Timeout: 15 min por execução
"""
import os
import yaml
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook


def _load_agencies_config() -> dict:
    """Carrega config de agências do YAML."""
    config_path = os.path.join(os.path.dirname(__file__), "config", "site_urls.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)["agencies"]


def create_scraper_dag(agency_key: str, agency_url: str):
    """Factory que cria uma DAG de scraping para uma agência."""

    @dag(
        dag_id=f"scrape_{agency_key}",
        description=f"Scrape notícias de {agency_key}",
        schedule="*/15 * * * *",
        start_date=datetime(2025, 1, 1),
        catchup=False,
        max_active_runs=1,  # Evita overlap
        tags=["scraper", "govbr", agency_key],
        default_args={
            "owner": "data-platform",
            "retries": 2,
            "retry_delay": timedelta(minutes=5),
            "retry_exponential_backoff": True,
            "max_retry_delay": timedelta(minutes=15),
            "execution_timeout": timedelta(minutes=15),
        },
    )
    def scraper_dag():

        @task
        def scrape(logical_date=None):
            """Scrape notícias da agência e insere no PostgreSQL."""
            # Bridge: extrair DATABASE_URL do Airflow connection
            hook = PostgresHook(postgres_conn_id="postgres_default")
            os.environ["DATABASE_URL"] = hook.get_uri()
            os.environ["STORAGE_BACKEND"] = "postgres"

            from data_platform.managers import StorageAdapter
            from data_platform.scrapers.scrape_manager import ScrapeManager

            # Janela: última 1 hora (com margem de segurança)
            min_date = (logical_date - timedelta(hours=1)).strftime("%Y-%m-%d")
            max_date = logical_date.strftime("%Y-%m-%d")

            storage = StorageAdapter()
            manager = ScrapeManager(storage)
            manager.run_scraper(
                agencies=[agency_key],
                min_date=min_date,
                max_date=max_date,
                sequential=True,
                allow_update=False,
            )

        scrape()

    return scraper_dag()


# Gerar DAGs dinamicamente
for key, url in _load_agencies_config().items():
    globals()[f"scrape_{key}"] = create_scraper_dag(key, url)
```

**Pontos importantes:**
- `max_active_runs=1` evita que execuções se sobreponham se uma demorar mais de 15 min
- Imports do `data_platform` dentro da task (lazy loading), não no nível do módulo
- `_load_agencies_config()` roda no parse time — precisa ser rápido (leitura de YAML local)
- A `agency_url` não é usada diretamente na DAG porque o `ScrapeManager` já carrega URLs do YAML internamente. Mas está disponível se precisarmos refatorar depois.

### Passo 4: Criar DAG EBC (`scrape_ebc.py`)

```python
"""DAG para scraping de notícias EBC (Agência Brasil, TV Brasil)."""
from datetime import datetime, timedelta
import os

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook


@dag(
    dag_id="scrape_ebc",
    description="Scrape notícias EBC (Agência Brasil, TV Brasil)",
    schedule="*/15 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["scraper", "ebc", "daily"],
    default_args={
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
)
def scrape_ebc_dag():

    @task
    def scrape_ebc(logical_date=None):
        hook = PostgresHook(postgres_conn_id="postgres_default")
        os.environ["DATABASE_URL"] = hook.get_uri()
        os.environ["STORAGE_BACKEND"] = "postgres"

        from data_platform.managers import StorageAdapter
        from data_platform.scrapers.ebc_scrape_manager import EBCScrapeManager

        min_date = (logical_date - timedelta(hours=1)).strftime("%Y-%m-%d")
        max_date = logical_date.strftime("%Y-%m-%d")

        storage = StorageAdapter()
        manager = EBCScrapeManager(storage)
        manager.run_scraper(min_date, max_date, sequential=True)

    scrape_ebc()

dag_instance = scrape_ebc_dag()
```

### Passo 5: Atualizar workflow de deploy

Em `.github/workflows/composer-deploy-dags.yaml`, garantir que a pasta `config/` seja incluída no rsync. O comando atual (`gsutil -m rsync -r -d`) já sincroniza recursivamente, então basta que `config/site_urls.yaml` esteja dentro de `src/data_platform/dags/`.

Verificar se o `-x "requirements\.txt$"` não exclui a pasta `config/` (não deve, é regex match em `requirements.txt` apenas).

### Passo 6: Deploy e teste incremental

1. **Deploy requirements**: Fazer merge do `requirements.txt` primeiro. Aguardar Composer instalar dependências (~10-20 min).
2. **Deploy com subset**: Modificar temporariamente `site_urls.yaml` na pasta `dags/config/` para conter apenas 3-5 agências (ex: `mec`, `mds`, `saude`).
3. **Trigger manual**: No Airflow UI, trigger manual das 3-5 DAGs de teste.
4. **Validar**: Confirmar que notícias aparecem no PostgreSQL.
5. **Expandir**: Restaurar `site_urls.yaml` completo e deployar.
6. **Monitorar**: Acompanhar por 2-3 dias antes de desativar GitHub Actions.

### Passo 7: Desativar scraper no GitHub Actions

Após validação, remover os jobs `scraper` e `ebc-scraper` do `main-workflow.yaml`. Manter os jobs downstream (cogfy-upload, enrich, embeddings, typesense-sync) — eles continuam rodando no horário atual, consumindo dados que agora chegam via Airflow.

## Riscos e Mitigações

| Risco | Mitigação |
|-------|-----------|
| Pacote `data-platform` não instala no Composer | Testar instalação local primeiro; fallback: copiar módulos para dags/ |
| 158 DAGs sobrecarregam o Airflow scheduler | `max_active_runs=1` + monitorar scheduler performance. Composer pode escalar workers. |
| Scraping a cada 15 min gera muitos requests em gov.br | `max_active_runs=1` impede acúmulo. WebScraper já tem delays (0.5-1.5s). Se necessário, aumentar intervalo. |
| `site_urls.yaml` na pasta dags fica desatualizado | Manter sincronizado via CI (copiar do source no deploy) ou usar script de sync |
| Import do `data_platform` falha no Airflow validation | Imports são lazy (dentro da `@task`), não no nível do módulo. Validation (py_compile) não executa tasks. |

## Verificação

1. **Após deploy de requirements**: `gcloud composer environments describe` mostra pacotes instalados
2. **Após deploy de DAGs**: Airflow UI lista ~158 DAGs com prefixo `scrape_`
3. **Após execução**: Query no PostgreSQL confirma novos registros:
   ```sql
   SELECT agency_key, COUNT(*), MAX(created_at)
   FROM news
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY agency_key
   ORDER BY COUNT(*) DESC;
   ```
4. **Monitoramento contínuo**: Airflow UI > DAGs > filtrar por tag `scraper` — verificar taxa de sucesso/falha
