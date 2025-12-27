# Plano de Migração: HuggingFace Dataset → PostgreSQL

> **Status**: Em planejamento
> **Início**: 2025-01-XX
> **Última atualização**: 2024-12-24

## Objetivo

Migrar o banco de dados principal do projeto DestaquesGovBr de HuggingFace Dataset para PostgreSQL (Cloud SQL), mantendo o HuggingFace como output de dados abertos com sync diário.

## Documentos Relacionados

| Documento | Descrição |
|-----------|-----------|
| [CONTEXT.md](./CONTEXT.md) | Contexto técnico completo para LLMs |
| [CHECKLIST.md](./CHECKLIST.md) | Verificações por fase |
| [DECISIONS.md](./DECISIONS.md) | Registro de decisões arquiteturais |
| [PROGRESS.md](./PROGRESS.md) | Log de progresso da implementação |
| [SCHEMA.md](./SCHEMA.md) | Schema do PostgreSQL |

---

## Visão Geral das Fases

```
┌─────────────────────────────────────────────────────────────────┐
│ Fase 0: Setup Inicial                                           │
│ - Estrutura do repositório                                      │
│ - Configuração básica                                           │
├─────────────────────────────────────────────────────────────────┤
│ Fase 1: Infraestrutura                                          │
│ - Cloud SQL (Terraform)                                         │
│ - Networking e Secrets                                          │
├─────────────────────────────────────────────────────────────────┤
│ Fase 2: PostgresManager                                         │
│ - Implementar PostgresManager                                   │
│ - Implementar StorageAdapter                                    │
│ - Testes unitários                                              │
├─────────────────────────────────────────────────────────────────┤
│ Fase 3: Migração de Dados                                       │
│ - Script de migração HF → PG                                    │
│ - Validação de integridade                                      │
├─────────────────────────────────────────────────────────────────┤
│ Fase 4: Dual-Write                                              │
│ - Pipeline escreve em ambos                                     │
│ - Monitoramento e validação                                     │
├─────────────────────────────────────────────────────────────────┤
│ Fase 4.7: Embeddings Semânticos                                 │
│ - Gerar embeddings para notícias de 2025                        │
│ - Armazenar no PostgreSQL (pgvector)                            │
│ - Sincronizar para Typesense                                    │
├─────────────────────────────────────────────────────────────────┤
│ Fase 5: PostgreSQL como Primary                                 │
│ - Switch para PG como fonte                                     │
│ - Sync job PG → HF                                              │
├─────────────────────────────────────────────────────────────────┤
│ Fase 6: Migração de Consumidores                                │
│ - Typesense lê do PG                                            │
│ - Outros consumidores                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Fase 0: Setup Inicial

**Objetivo**: Estruturar o repositório data-platform e configurações básicas.

### Tarefas

- [ ] 0.1 Criar estrutura de diretórios do repositório
- [ ] 0.2 Configurar pyproject.toml com dependências
- [ ] 0.3 Criar CLAUDE.md com contexto do projeto
- [ ] 0.4 Inicializar git e configurar .gitignore
- [ ] 0.5 Criar estrutura de testes

### Estrutura Alvo

```
data-platform/
├── _plan/                    # Documentação do plano (este diretório)
├── src/
│   └── data_platform/
│       ├── __init__.py
│       ├── managers/
│       │   ├── __init__.py
│       │   ├── postgres_manager.py
│       │   ├── dataset_manager.py
│       │   └── storage_adapter.py
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── scraper/
│       │   ├── enrichment/
│       │   └── hf_sync/
│       └── models/
│           ├── __init__.py
│           └── news.py
├── tests/
│   ├── __init__.py
│   ├── test_postgres_manager.py
│   └── test_storage_adapter.py
├── scripts/
│   ├── migrate_hf_to_postgres.py
│   └── validate_migration.py
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

### Critérios de Conclusão

- [ ] Estrutura de diretórios criada
- [ ] Poetry/pip install funciona
- [ ] Testes podem ser executados (mesmo que vazios)
- [ ] Documentação atualizada (README.md, docs/)
- [ ] PR criado documentando progresso da fase

---

## Fase 1: Infraestrutura

**Objetivo**: Provisionar Cloud SQL e configurar acesso seguro.

### Tarefas

- [ ] 1.1 Criar cloud_sql.tf no repo destaquesgovbr/infra
- [ ] 1.2 Configurar networking (VPC, firewall)
- [ ] 1.3 Criar secrets no Secret Manager
- [ ] 1.4 Configurar Cloud SQL Proxy para CI/CD
- [ ] 1.5 Aplicar Terraform e validar conexão

### Terraform Resources

```hcl
# Cloud SQL Instance
google_sql_database_instance.govbrnews

# Database
google_sql_database.govbrnews

# User
google_sql_user.app_user

# Secrets
google_secret_manager_secret.database_url
```

### Variáveis de Ambiente

| Variável | Onde Definir | Descrição |
|----------|--------------|-----------|
| `DATABASE_URL` | Secret Manager | Connection string completa |
| `GOVBRNEWS_DB_HOST` | Secret Manager | Host do Cloud SQL |
| `GOVBRNEWS_DB_NAME` | terraform.tfvars | Nome do database |

### Restrições

- A infraestrutura é gerida pelo workflow CICD apenas e não executando terraform apply localmente

### Critérios de Conclusão

- [ ] Cloud SQL provisionado e acessível
- [ ] Conexão via Cloud SQL Proxy funciona
- [ ] Secrets configurados no Secret Manager
- [ ] GitHub Actions consegue acessar o banco
- [ ] Documentação atualizada (docs/database/, infra/docs/)
- [ ] PR criado documentando progresso da fase

---

## Fase 2: PostgresManager

**Objetivo**: Implementar a camada de acesso ao PostgreSQL com interface compatível com DatasetManager.

### Tarefas

- [ ] 2.1 Implementar PostgresManager com métodos básicos (insert, update, get)
- [ ] 2.2 Implementar cache de agencies e themes
- [ ] 2.3 Implementar StorageAdapter com suporte a backends
- [ ] 2.4 Criar testes unitários
- [ ] 2.5 Criar testes de integração

### Interface PostgresManager

```python
class PostgresManager:
    def insert(self, new_data: OrderedDict, allow_update: bool = False) -> int
    def update(self, updated_df: pd.DataFrame) -> int
    def get(self, min_date: str, max_date: str, agency: str = None) -> pd.DataFrame
    def get_by_unique_id(self, unique_id: str) -> dict
    def get_records_for_hf_sync(self, since: datetime = None) -> pd.DataFrame
    def mark_as_synced_to_hf(self, unique_ids: list[str]) -> None
```

### StorageAdapter Backends

```python
class StorageBackend(Enum):
    HUGGINGFACE = "huggingface"
    POSTGRES = "postgres"
    DUAL_WRITE = "dual_write"
```

### Critérios de Conclusão

- [ ] PostgresManager passa todos os testes unitários
- [ ] StorageAdapter funciona com todos os backends
- [ ] Testes de integração passam com banco real
- [ ] Cobertura de testes > 80%
- [ ] Documentação atualizada (docs/development/, API docs)
- [ ] PR criado documentando progresso da fase

---

## Fase 3: Migração de Dados

**Objetivo**: Migrar dados existentes do HuggingFace para PostgreSQL.

### Tarefas

- [ ] 3.1 Criar tabelas no PostgreSQL (agencies, themes, news)
- [ ] 3.2 Popular tabela agencies a partir de agencies.yaml
- [ ] 3.3 Popular tabela themes a partir de themes_tree.yaml
- [ ] 3.4 Migrar registros de news do HuggingFace
- [ ] 3.5 Validar integridade dos dados migrados

### Script de Migração

```bash
# 1. Criar schema
python scripts/create_schema.py

# 2. Popular dados mestres
python scripts/populate_agencies.py
python scripts/populate_themes.py

# 3. Migrar news
python scripts/migrate_hf_to_postgres.py --batch-size 1000

# 4. Validar
python scripts/validate_migration.py
```

### Métricas de Validação

| Métrica | Esperado |
|---------|----------|
| Total de registros | ~300.000 |
| Registros com theme | > 95% |
| Registros com agency válida | 100% |
| Campos obrigatórios preenchidos | 100% |

### Critérios de Conclusão

- [ ] Todas as tabelas criadas
- [ ] Agencies e themes populados
- [ ] Todos os registros migrados
- [ ] Validação retorna 100% de integridade
- [ ] Contagem PG == contagem HF
- [ ] Documentação atualizada (scripts de migração, troubleshooting)
- [ ] PR criado documentando progresso da fase

---

## Fase 4: Dual-Write

**Objetivo**: Pipeline escreve simultaneamente em PostgreSQL e HuggingFace para validação.

### Tarefas

- [ ] 4.1 Configurar STORAGE_BACKEND=dual_write no GitHub Actions
- [ ] 4.2 Atualizar workflows para usar StorageAdapter
- [ ] 4.3 Executar pipeline completo em modo dual-write
- [ ] 4.4 Monitorar por 3-5 dias
- [ ] 4.5 Validar consistência entre os dois backends

### Configuração do Workflow

```yaml
env:
  STORAGE_BACKEND: dual_write
  STORAGE_READ_FROM: huggingface  # Ainda lê do HF
  DATABASE_URL: ${{ secrets.DATABASE_URL }}
  HF_TOKEN: ${{ secrets.HF_TOKEN }}
```

### Monitoramento

- [ ] Logs de escrita em ambos backends
- [ ] Alertas de falha de escrita
- [ ] Comparação diária de contagens
- [ ] Amostragem de registros para validação

### Critérios de Conclusão

- [ ] Pipeline executou 5+ dias em dual-write sem erros
- [ ] Contagens coincidem diariamente
- [ ] Amostragem mostra 100% de consistência
- [ ] Nenhum erro de escrita em nenhum backend
- [ ] Documentação atualizada (monitoramento, validação)
- [ ] PR criado documentando progresso da fase

### Sub-plano: Adaptação do Scraper para StorageAdapter

> **Criado em**: 2024-12-25
> **Objetivo**: Integrar o StorageAdapter (PR #5) no scraper para habilitar dual-write

#### Contexto: Arquivos que usam DatasetManager no Scraper

| Arquivo | Uso | Métodos |
|---------|-----|---------|
| `src/main.py` | Cria DatasetManager | Constructor |
| `src/scraper/scrape_manager.py` | Insere notícias | `.insert()` |
| `src/scraper/ebc_scrape_manager.py` | Insere notícias EBC | `.insert()` |
| `src/enrichment_manager.py` | Enriquece com temas | `._load_existing_dataset()`, `.update()`, `._push_dataset_and_csvs()` |
| `src/upload_to_cogfy_manager.py` | Upload Cogfy | `._load_existing_dataset()` |
| `src/augmentation_manager.py` | Augmentação | `.get()`, custom update |

#### CLI do Scraper (para testes)

```bash
# Scrape com 1 órgão, período específico
python src/main.py scrape --start-date 2024-12-20 --end-date 2024-12-20 --agencies gestao

# Scrape EBC
python src/main.py scrape-ebc --start-date 2024-12-20 --end-date 2024-12-20

# Augment
python src/main.py augment --start-date 2024-12-20 --end-date 2024-12-20
```

#### Etapa 4.1: Criar StorageWrapper no Scraper

**Arquivo**: `scraper/src/storage_wrapper.py`

```python
"""
Storage wrapper that uses StorageAdapter when available,
falls back to DatasetManager for legacy operations.
"""
import os
from typing import Optional, OrderedDict
import pandas as pd

class StorageWrapper:
    def __init__(self):
        self.backend = os.getenv("STORAGE_BACKEND", "huggingface")

        if self.backend in ("postgres", "dual_write"):
            from data_platform.managers.storage_adapter import StorageAdapter
            self._storage = StorageAdapter()
            self._use_adapter = True
        else:
            from dataset_manager import DatasetManager
            self._storage = DatasetManager()
            self._use_adapter = False

    def insert(self, new_data: OrderedDict, allow_update: bool = False) -> int:
        return self._storage.insert(new_data, allow_update=allow_update)

    def update(self, updated_df: pd.DataFrame) -> int:
        return self._storage.update(updated_df)

    def get(self, min_date: str, max_date: str, agency: Optional[str] = None) -> pd.DataFrame:
        return self._storage.get(min_date, max_date, agency=agency)

    # Legacy methods for enrichment (only work with DatasetManager)
    def _load_existing_dataset(self):
        if self._use_adapter:
            raise NotImplementedError("Use get() instead")
        return self._storage._load_existing_dataset()

    def _push_dataset_and_csvs(self, dataset):
        if self._use_adapter:
            raise NotImplementedError("Push is automatic with StorageAdapter")
        return self._storage._push_dataset_and_csvs(dataset)
```

#### Etapa 4.2: Modificar main.py

```python
# Antes:
from dataset_manager import DatasetManager
dataset_manager = DatasetManager()

# Depois:
from storage_wrapper import StorageWrapper
storage = StorageWrapper()
```

#### Etapa 4.3: Teste Local (Docker)

```bash
# 1. Subir PostgreSQL local
cd /path/to/data-platform
docker-compose up -d

# 2. Configurar ambiente
export DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"
export STORAGE_BACKEND="dual_write"
export STORAGE_READ_FROM="huggingface"
export HF_TOKEN="..."

# 3. Testar scraper com 1 órgão, 1 dia
cd /path/to/scraper
python src/main.py scrape \
  --start-date 2024-12-20 \
  --end-date 2024-12-20 \
  --agencies gestao \
  --allow-update
```

#### Etapa 4.4: Validar Dados no PostgreSQL

```sql
-- Conectar ao PostgreSQL local
psql "postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"

-- Verificar inserções recentes
SELECT COUNT(*) FROM news WHERE extracted_at >= NOW() - INTERVAL '1 hour';

-- Verificar temas preenchidos
SELECT COUNT(*) FROM news WHERE theme_l1_id IS NOT NULL;

-- Amostra de dados
SELECT unique_id, agency_key, title, image_url, video_url, theme_l1_id
FROM news ORDER BY created_at DESC LIMIT 5;
```

#### Etapa 4.5: Configurar GitHub Actions

```yaml
# .github/workflows/pipeline-steps.yaml
jobs:
  scraper:
    env:
      STORAGE_BACKEND: dual_write
      STORAGE_READ_FROM: huggingface
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
    steps:
      - name: Setup Cloud SQL Auth
        run: |
          export DATABASE_URL=$(gcloud secrets versions access latest --secret=destaquesgovbr-postgres-connection-string)
```

#### Etapa 4.6: Monitoramento (5 dias)

**Query de validação diária:**
```sql
SELECT DATE(published_at) as dt, COUNT(*)
FROM news
WHERE published_at >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY dt ORDER BY dt DESC;
```

**Rollback se necessário:**
```yaml
STORAGE_BACKEND: huggingface  # Voltar para HF-only
```

#### Checklist de Execução

- [ ] Criar `src/storage_wrapper.py` no scraper
- [ ] Modificar `src/main.py` para usar StorageWrapper
- [ ] Instalar data-platform como dependência no scraper
- [ ] PostgreSQL local rodando (docker-compose)
- [ ] Teste scrape com 1 órgão, 1 dia
- [ ] Validar dados no PostgreSQL local
- [ ] Teste scrape-ebc
- [ ] Modificar workflow para dual_write
- [ ] Trigger manual para teste em produção
- [ ] Monitorar 5 dias
- [ ] Aprovar para próxima fase

---

## Fase 4.5: Consolidação do Scraper no Data-Platform

> **Criado em**: 2024-12-26
> **Objetivo**: Mover todo o código do repositório `scraper` para `data-platform`, eliminando dependências cross-repo e simplificando CI/CD.

### Motivação

1. **Problema do Docker Build**: O path `../data-platform` não existe no contexto do Docker
2. **Complexidade de dependências**: Dois repos com versões conflitantes de bibliotecas
3. **CI/CD fragmentado**: Workflows separados, difícil manter sincronizados
4. **O scraper é específico**: Não é biblioteca genérica, é específico para gov.br/EBC

### Arquitetura Atual vs Futura

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ARQUITETURA ATUAL                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐         ┌──────────────────┐                 │
│  │     scraper      │ ──────► │   HuggingFace    │                 │
│  │  (repo separado) │         │  (source of truth)│                 │
│  └────────┬─────────┘         └────────┬─────────┘                 │
│           │ dependência                │                            │
│           ▼                            ▼                            │
│  ┌──────────────────┐         ┌──────────────────┐                 │
│  │  data-platform   │         │   Consumidores   │                 │
│  │   (PostgreSQL)   │         │ Typesense/Qdrant │                 │
│  └──────────────────┘         └──────────────────┘                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

                              ▼▼▼

┌─────────────────────────────────────────────────────────────────────┐
│                        ARQUITETURA FUTURA                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────────────┐              │
│  │              data-platform (monorepo)            │              │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐ │              │
│  │  │  Scrapers  │  │  Storage   │  │  Pipelines │ │              │
│  │  │ gov.br/EBC │  │ PostgreSQL │  │ Enrichment │ │              │
│  │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │              │
│  │        │               │               │        │              │
│  │        └───────────────┴───────────────┘        │              │
│  └──────────────────────────────────────────────────┘              │
│                          │                                          │
│           ┌──────────────┼──────────────┐                          │
│           ▼              ▼              ▼                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │
│  │  PostgreSQL  │ │  HuggingFace │ │ Consumidores │                │
│  │   (primary)  │ │  (sync/open) │ │  Typesense   │                │
│  └──────────────┘ └──────────────┘ └──────────────┘                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Nova Estrutura de Diretórios

```
data-platform/
├── _plan/                          # Plano de migração
├── src/
│   └── data_platform/
│       ├── __init__.py
│       ├── cli.py                  # CLI unificada (novo entry point)
│       ├── managers/               # Storage backends
│       │   ├── __init__.py
│       │   ├── postgres_manager.py
│       │   ├── dataset_manager.py  # ◄── Movido do scraper
│       │   └── storage_adapter.py
│       ├── scrapers/               # ◄── Movido do scraper
│       │   ├── __init__.py
│       │   ├── webscraper.py
│       │   ├── scrape_manager.py
│       │   ├── ebc_webscraper.py
│       │   ├── ebc_scrape_manager.py
│       │   └── config/
│       │       ├── site_urls.yaml
│       │       └── agencies.yaml
│       ├── enrichment/             # ◄── Movido do scraper
│       │   ├── __init__.py
│       │   ├── augmentation_manager.py
│       │   ├── classifier_summarizer.py
│       │   └── config/
│       │       ├── themes_tree.yaml
│       │       └── themes_level_1.yaml
│       ├── cogfy/                  # ◄── Movido do scraper
│       │   ├── __init__.py
│       │   ├── cogfy_manager.py
│       │   ├── upload_manager.py
│       │   └── enrichment_manager.py
│       ├── jobs/
│       │   └── hf_sync/
│       └── models/
│           └── news.py
├── tests/                          # Testes consolidados
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/
│   ├── migrate_hf_to_postgres.py
│   └── validate_migration.py
├── docker/
│   └── Dockerfile
├── .github/
│   └── workflows/                  # Workflows migrados
│       ├── main-workflow.yaml
│       ├── pipeline-steps.yaml
│       └── docker-build.yaml
├── pyproject.toml                  # Dependências consolidadas
├── CLAUDE.md
└── README.md
```

### Etapas de Implementação

#### 4.5.1: Mover Código do Scraper

| Origem (scraper) | Destino (data-platform) |
|------------------|------------------------|
| `src/scraper/webscraper.py` | `src/data_platform/scrapers/webscraper.py` |
| `src/scraper/scrape_manager.py` | `src/data_platform/scrapers/scrape_manager.py` |
| `src/scraper/ebc_webscraper.py` | `src/data_platform/scrapers/ebc_webscraper.py` |
| `src/scraper/ebc_scrape_manager.py` | `src/data_platform/scrapers/ebc_scrape_manager.py` |
| `src/scraper/site_urls.yaml` | `src/data_platform/scrapers/config/site_urls.yaml` |
| `src/scraper/agencies.yaml` | `src/data_platform/scrapers/config/agencies.yaml` |
| `src/dataset_manager.py` | `src/data_platform/managers/dataset_manager.py` |
| `src/enrichment/` | `src/data_platform/enrichment/` |
| `src/cogfy_manager.py` | `src/data_platform/cogfy/cogfy_manager.py` |
| `src/upload_to_cogfy_manager.py` | `src/data_platform/cogfy/upload_manager.py` |
| `src/enrichment_manager.py` | `src/data_platform/cogfy/enrichment_manager.py` |
| `tests/` | `tests/` (merge) |

#### 4.5.2: Atualizar pyproject.toml

Adicionar dependências do scraper ao data-platform:

```toml
[tool.poetry.dependencies]
python = "^3.11"

# Database
psycopg2-binary = "^2.9.9"
sqlalchemy = "^2.0.23"

# HuggingFace
datasets = ">=3.1.0"
huggingface-hub = ">=0.20.0"

# Data processing
pandas = ">=2.1.4"
pyarrow = ">=15.0.0"

# Web scraping (do scraper)
beautifulsoup4 = "^4.12.3"
requests = "^2.32.3"
retry = "^0.9.2"
markdownify = "^0.14.1"
markdown = "^3.7"

# AI/LLM (do scraper)
langchain = "^0.3.3"
langchain-community = "^0.3.2"
langchain-openai = "^0.2.3"
openai = "^1.52.0"

# Cogfy (do scraper)
algoliasearch = "^4.13.0"

# Configuration
pydantic = "^2.5.3"
pydantic-settings = "^2.1.0"
python-dotenv = "^1.0.0"
pyyaml = "^6.0.2"

# Utilities
tqdm = "^4.66.1"
loguru = "^0.7.2"
typer = "^0.9.0"
```

#### 4.5.3: Criar CLI Unificada

**Arquivo**: `src/data_platform/cli.py`

```python
import typer
from datetime import datetime, timedelta

app = typer.Typer(name="data-platform", help="Data platform for DestaquesGovBr")

@app.command()
def scrape(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
    agencies: str = typer.Option(None, help="Comma-separated agency codes"),
    allow_update: bool = typer.Option(False, help="Allow updating existing records"),
    sequential: bool = typer.Option(True, help="Process agencies sequentially"),
):
    """Scrape gov.br news from specified agencies."""
    from data_platform.scrapers.scrape_manager import ScrapeManager
    from data_platform.managers import StorageAdapter

    storage = StorageAdapter()
    manager = ScrapeManager(storage)
    agency_list = agencies.split(",") if agencies else None
    manager.run_scraper(agency_list, start_date, end_date or start_date, sequential, allow_update)

@app.command()
def scrape_ebc(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
    allow_update: bool = typer.Option(False, help="Allow updating existing records"),
):
    """Scrape EBC (Agência Brasil, TV Brasil) news."""
    from data_platform.scrapers.ebc_scrape_manager import EBCScrapeManager
    from data_platform.managers import StorageAdapter

    storage = StorageAdapter()
    manager = EBCScrapeManager(storage)
    manager.run_scraper(start_date, end_date or start_date, True, allow_update)

@app.command()
def upload_cogfy(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
):
    """Upload news to Cogfy for AI enrichment."""
    from data_platform.cogfy.upload_manager import UploadToCogfyManager
    manager = UploadToCogfyManager()
    manager.upload(start_date, end_date or start_date)

@app.command()
def enrich(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
):
    """Enrich news with AI-generated themes from Cogfy."""
    from data_platform.cogfy.enrichment_manager import EnrichmentManager
    manager = EnrichmentManager()
    manager.enrich(start_date, end_date or start_date)

@app.command()
def sync_hf():
    """Sync PostgreSQL data to HuggingFace."""
    from data_platform.jobs.hf_sync.sync_job import sync_to_huggingface
    sync_to_huggingface()

@app.command()
def migrate_hf_to_pg(
    batch_size: int = typer.Option(1000, help="Batch size for migration"),
    max_records: int = typer.Option(None, help="Max records to migrate (for testing)"),
):
    """Migrate data from HuggingFace to PostgreSQL."""
    from scripts.migrate_hf_to_postgres import main
    main(batch_size=batch_size, max_records=max_records)

if __name__ == "__main__":
    app()
```

**Entry point em pyproject.toml**:

```toml
[tool.poetry.scripts]
data-platform = "data_platform.cli:app"
```

**Uso**:

```bash
# Scrape gov.br
data-platform scrape --start-date 2024-12-20 --agencies gestao

# Scrape EBC
data-platform scrape-ebc --start-date 2024-12-20

# Upload para Cogfy
data-platform upload-cogfy --start-date 2024-12-20

# Enriquecer com temas AI
data-platform enrich --start-date 2024-12-20

# Sync para HuggingFace
data-platform sync-hf
```

#### 4.5.4: Migrar GitHub Actions

**Mover workflows do scraper para data-platform**:

```yaml
# .github/workflows/pipeline-steps.yaml
name: Daily Pipeline

on:
  workflow_call:
    inputs:
      start_date:
        required: true
        type: string
      end_date:
        required: true
        type: string

jobs:
  scrape-govbr:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/destaquesgovbr/data-platform:latest
    env:
      STORAGE_BACKEND: dual_write
      STORAGE_READ_FROM: huggingface
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
    steps:
      - name: Scrape gov.br news
        run: data-platform scrape --start-date ${{ inputs.start_date }} --end-date ${{ inputs.end_date }}

  scrape-ebc:
    runs-on: ubuntu-latest
    needs: scrape-govbr
    container:
      image: ghcr.io/destaquesgovbr/data-platform:latest
    env:
      STORAGE_BACKEND: dual_write
      STORAGE_READ_FROM: huggingface
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
    steps:
      - name: Scrape EBC news
        run: data-platform scrape-ebc --start-date ${{ inputs.start_date }} --end-date ${{ inputs.end_date }} --allow-update

  upload-cogfy:
    runs-on: ubuntu-latest
    needs: [scrape-govbr, scrape-ebc]
    container:
      image: ghcr.io/destaquesgovbr/data-platform:latest
    env:
      COGFY_API_KEY: ${{ secrets.COGFY_API_KEY }}
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
    steps:
      - name: Upload to Cogfy
        run: data-platform upload-cogfy --start-date ${{ inputs.start_date }} --end-date ${{ inputs.end_date }}

  enrich-themes:
    runs-on: ubuntu-latest
    needs: upload-cogfy
    container:
      image: ghcr.io/destaquesgovbr/data-platform:latest
    env:
      COGFY_API_KEY: ${{ secrets.COGFY_API_KEY }}
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
      STORAGE_BACKEND: dual_write
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
    steps:
      - name: Wait for Cogfy processing
        run: sleep 1200  # 20 minutes
      - name: Enrich with AI themes
        run: data-platform enrich --start-date ${{ inputs.start_date }} --end-date ${{ inputs.end_date }}
```

#### 4.5.5: Atualizar Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc g++ \
    libffi-dev libssl-dev \
    curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --no-ansi

# Copy application code
COPY src/ src/
COPY scripts/ scripts/

# Install the package
RUN poetry install --no-interaction --no-ansi

# Default command
CMD ["data-platform", "--help"]
```

#### 4.5.6: Testar Pipeline Consolidado

```bash
# 1. Build local
cd data-platform
docker build -t data-platform:test .

# 2. Testar CLI
docker run --rm \
  -e STORAGE_BACKEND=huggingface \
  -e HF_TOKEN=$HF_TOKEN \
  data-platform:test data-platform scrape --start-date 2024-12-20 --agencies gestao

# 3. Testar dual-write
docker run --rm \
  -e STORAGE_BACKEND=dual_write \
  -e DATABASE_URL=$DATABASE_URL \
  -e HF_TOKEN=$HF_TOKEN \
  data-platform:test data-platform scrape --start-date 2024-12-20 --agencies gestao
```

### Checklist de Execução

- [ ] 4.5.1: Criar estrutura de diretórios no data-platform
- [ ] 4.5.1: Mover arquivos do scraper
- [ ] 4.5.1: Ajustar imports em todos os arquivos movidos
- [ ] 4.5.2: Atualizar pyproject.toml com todas as dependências
- [ ] 4.5.2: Rodar poetry lock e verificar conflitos
- [ ] 4.5.3: Criar cli.py com todos os comandos
- [ ] 4.5.3: Testar CLI localmente
- [ ] 4.5.4: Copiar workflows do scraper
- [ ] 4.5.4: Atualizar workflows para usar nova CLI
- [ ] 4.5.5: Atualizar Dockerfile
- [ ] 4.5.5: Build e push nova imagem
- [ ] 4.5.6: Testar pipeline completo localmente
- [ ] 4.5.6: Testar pipeline em GitHub Actions
- [ ] 4.5.7: Arquivar repositório scraper (read-only)
- [ ] 4.5.7: Atualizar README do scraper com redirect

### Critérios de Conclusão

- [ ] Todo código do scraper movido para data-platform
- [ ] CLI unificada funciona com todos os comandos
- [ ] Docker build funciona sem erros
- [ ] GitHub Actions executa pipeline completo
- [ ] Testes passam (unit + integration)
- [ ] Repositório scraper arquivado
- [ ] Documentação atualizada

---

## Fase 4.7: Embeddings Semânticos

**Objetivo**: Adicionar geração de embeddings semânticos para notícias de 2025 e sincronização com Typesense para busca semântica.

> **IMPORTANTE**: Esta fase processa **apenas notícias de 2025** pois somente elas possuem resumos AI-gerados pelo Cogfy. Notícias anteriores não serão processadas nesta fase.

### Tarefas

- [ ] 4.7.1 Habilitar pgvector extension no Cloud SQL
- [ ] 4.7.2 Adicionar colunas de embedding à tabela news
- [ ] 4.7.3 Criar índices HNSW para busca vetorial
- [ ] 4.7.4 Implementar EmbeddingGenerator
- [ ] 4.7.5 Implementar TypesenseSyncManager
- [ ] 4.7.6 Adicionar comandos CLI (generate-embeddings, sync-embeddings-to-typesense)
- [ ] 4.7.7 Escrever testes automatizados (unit + integration)
- [ ] 4.7.8 Atualizar workflow GitHub Actions
- [ ] 4.7.9 Atualizar schema do Typesense
- [ ] 4.7.10 Testar localmente com Docker (PostgreSQL + Typesense)
- [ ] 4.7.11 Backfill embeddings para 2025

### Arquitetura

```
Pipeline Diário:
  scraper → PostgreSQL
      ↓
  upload-cogfy → Cogfy API (gera summary)
      ↓
  [wait 20 min]
      ↓
  enrich-themes → PostgreSQL (themes + summary)
      ↓
  [NOVO] generate-embeddings → PostgreSQL (embeddings de title + summary)
      ↓
  [NOVO] sync-embeddings-to-typesense → Typesense (campo content_embedding)
```

### Decisões Técnicas

| Decisão | Escolha | Justificativa |
|---------|---------|---------------|
| **Modelo** | paraphrase-multilingual-mpnet-base-v2 (768 dims) | Já usado para temas, excelente português, local (grátis), consistente |
| **Input** | `title + " " + summary` | Summary é AI-generated (Cogfy), mais semântico que content bruto |
| **Escopo** | **Apenas 2025** | Somente 2025 tem summaries do Cogfy |
| **Timing** | Job separado APÓS enrich-themes | Garante que summary está disponível |
| **Storage** | PostgreSQL (pgvector) + Typesense | PG para queries avançadas, Typesense para MCP Server |
| **Sync** | Job separado PG → Typesense | Modular, permite re-sync sem re-gerar |

### Implementação

#### 4.7.1-4.7.3: Database Schema (PostgreSQL)

**Migrations**:
1. `scripts/migrations/001_add_pgvector_extension.sql` - Habilitar pgvector
2. `scripts/migrations/002_add_embedding_column.sql` - Adicionar colunas (content_embedding, embedding_generated_at)
3. `scripts/migrations/003_create_embedding_index.sql` - Criar índices HNSW

**Terraform Update** (`infra/terraform/cloud_sql.tf`):
```hcl
# Phase 4.7: Enable pgvector for embeddings
database_flags {
  name  = "cloudsql.enable_pgvector"
  value = "on"
}
```

**Estimativa de Storage**:
- Embeddings (~30k records de 2025): ~90 MB
- HNSW index: ~200 MB
- **Total adicional**: ~300 MB

#### 4.7.4-4.7.6: Python Implementation

**Novos arquivos**:
- `src/data_platform/jobs/embeddings/__init__.py`
- `src/data_platform/jobs/embeddings/embedding_generator.py` - Gera embeddings usando sentence-transformers
- `src/data_platform/jobs/embeddings/typesense_sync.py` - Sync embeddings para Typesense

**Funcionalidades**:
- **EmbeddingGenerator**:
  - Carrega modelo `paraphrase-multilingual-mpnet-base-v2`
  - Busca notícias de 2025 sem embeddings do PostgreSQL
  - Gera embeddings de `title + " " + summary` (fallback para content se sem summary)
  - Atualiza PostgreSQL com embeddings + timestamp
  - Performance: ~30-40 records/sec (CPU)

- **TypesenseSyncManager**:
  - Busca notícias com embeddings novos/atualizados
  - Sync incremental baseado em `embedding_generated_at`
  - Batch upsert (1000 docs por vez)
  - Usa secrets existentes do Typesense (typesense-api-key)

**CLI Commands** (adicionar em `src/data_platform/cli.py`):
```bash
# Gerar embeddings para notícias de 2025
data-platform generate-embeddings --start-date 2025-01-01 --end-date 2025-12-31

# Sync para Typesense
data-platform sync-embeddings-to-typesense --start-date 2025-01-01
```

**Model Update** (`src/data_platform/models/news.py`):
```python
# Embedding fields (Phase 4.7)
content_embedding: Optional[List[float]] = None  # 768-dimensional vector
embedding_generated_at: Optional[datetime] = None
```

#### 4.7.7: Testes Automatizados

**Arquivos de teste**:
- `tests/unit/test_embedding_generator.py` - Testa geração de embeddings, preparação de texto, similaridade
- `tests/unit/test_typesense_sync.py` - Testa preparação de documentos, validação de schema, parsing
- `tests/integration/test_embedding_workflow.py` - Testa workflow completo com PostgreSQL local

**Casos de teste**:
- Preparação de texto para embedding (title + summary, fallback)
- Geração de embeddings (mock do modelo)
- Similaridade entre textos relacionados
- Preparação de documentos Typesense
- Validação de schema
- Workflow completo (10 registros)

**Teste local com Docker**:
```bash
# 1. PostgreSQL com pgvector
docker run -d --name postgres-pgvector \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=destaquesgovbr \
  -p 5432:5432 \
  pgvector/pgvector:pg15

# 2. Typesense local (do repo typesense)
cd /Users/nitai/Dropbox/dev-mgi/destaquesgovbr/typesense
./run-typesense-server.sh

# 3. Run migrations
psql -h localhost -U postgres -d destaquesgovbr -f scripts/migrations/*.sql

# 4. Test embedding generation
export DATABASE_URL="postgresql://postgres:password@localhost:5432/destaquesgovbr"
poetry run data-platform generate-embeddings --start-date 2025-01-01 --max-records 100

# 5. Test Typesense sync
export TYPESENSE_HOST=localhost TYPESENSE_PORT=8108 TYPESENSE_API_KEY=...
poetry run data-platform sync-embeddings-to-typesense --start-date 2025-01-01
```

#### 4.7.8: GitHub Actions Workflow

**Adicionar 2 novos jobs em `.github/workflows/pipeline-steps.yaml`** (após `enrich-themes`):

```yaml
  generate-embeddings:
    name: Generate Semantic Embeddings
    runs-on: ubuntu-latest
    needs: [enrich-themes]
    steps:
      - name: Generate embeddings for 2025 news
        run: |
          docker run --rm \
            -e DATABASE_URL="${{ secrets.DATABASE_URL }}" \
            ghcr.io/destaquesgovbr/data-platform:latest \
            data-platform generate-embeddings \
              --start-date "${{ inputs.start_date }}" \
              --end-date "${{ inputs.end_date }}"

  sync-embeddings-to-typesense:
    name: Sync Embeddings to Typesense
    runs-on: ubuntu-latest
    needs: [generate-embeddings]
    steps:
      - name: Sync embeddings to Typesense
        run: |
          docker run --rm \
            -e DATABASE_URL="${{ secrets.DATABASE_URL }}" \
            -e TYPESENSE_API_KEY="$(gcloud secrets versions access latest --secret=typesense-api-key)" \
            -e TYPESENSE_HOST="typesense-server.southamerica-east1-a.c.inspire-7-finep.internal" \
            -e TYPESENSE_PORT="8108" \
            ghcr.io/destaquesgovbr/data-platform:latest \
            data-platform sync-embeddings-to-typesense \
              --start-date "${{ inputs.start_date }}" \
              --end-date "${{ inputs.end_date }}"
```

**Atualizar job `pipeline-summary`**:
```yaml
needs: [scraper, ebc-scraper, upload-to-cogfy, enrich-themes, generate-embeddings, sync-embeddings-to-typesense]
```

#### 4.7.9: Dependencies & Docker

**pyproject.toml** (adicionar após scipy):
```toml
# Machine Learning (Phase 4.7 - Embeddings)
sentence-transformers = "^2.2.2"
torch = {version = "^2.0.0", source = "pytorch-cpu"}

[[tool.poetry.source]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
priority = "explicit"
```

**Dockerfile** (adicionar antes do CMD - **PRE-DOWNLOAD CONFIRMADO**):
```dockerfile
# Phase 4.7: Pre-download embedding model to cache in Docker layer
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')"
```

**Tamanho adicional da imagem**:
- sentence-transformers: ~50 MB
- torch (CPU-only): ~150 MB
- Model weights: ~420 MB
- **Total**: ~620 MB

#### 4.7.10: Typesense Schema Update

**Atualizar `typesense/src/typesense_dgb/collection.py`** (adicionar campo):
```python
{
    "name": "content_embedding",
    "type": "float[]",
    "facet": False,
    "optional": True,
    "index": True,
    "num_dim": 768  # Required for vector fields
},
```

**⚠️ IMPORTANTE**: Typesense não suporta ALTER schema. Deve **recriar collection** (DESTRUTIVO).

**Script de update** (rodar UMA VEZ):
```python
# 1. Backup data (export via PostgreSQL)
# 2. Delete collection: client.collections['news'].delete()
# 3. Create com novo schema (inclui content_embedding)
# 4. Full sync from PostgreSQL
```

#### 4.7.11: Secrets (Já existem!)

**Usar secrets existentes do infra**:
- `typesense-api-key` (já existe em `infra/terraform/secrets.tf`, linha 62)
- `typesense-write-conn` (já existe, linha 142)
- GitHub Actions já tem acesso (linha 87, 161)

**Sem necessidade de criar novos secrets!**

### Deployment Strategy

#### Fase 1: Infrastructure Setup
1. PR Terraform: Habilitar pgvector no Cloud SQL
2. Aplicar Terraform (via CI/CD)
3. Rodar migrations (001, 002, 003)
4. Build Docker image com ML dependencies

#### Fase 2: Code Implementation
1. Implementar EmbeddingGenerator e TypesenseSyncManager
2. Adicionar CLI commands
3. Escrever testes (unit + integration)
4. Testar localmente (Docker PostgreSQL + Typesense)
5. Code review e merge PR

#### Fase 3: Typesense Schema Update
1. Backup Typesense data
2. Atualizar collection schema (adicionar content_embedding)
3. Delete + recreate collection
4. Full sync PG → Typesense

#### Fase 4: Production Integration
1. Adicionar jobs ao workflow GitHub Actions
2. Trigger manual teste (1 dia de 2025)
3. Monitorar 1 semana
4. Sign-off

### Backfill Embeddings (2025)

**Escopo**: ~30.000 notícias de 2025 (apenas elas têm summary do Cogfy)

**Script**: `scripts/backfill_embeddings.sh`
```bash
#!/bin/bash
# Backfill embeddings para 2025

START_DATE="2025-01-01"
END_DATE="2025-12-31"

poetry run data-platform generate-embeddings \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"

poetry run data-platform sync-embeddings-to-typesense \
  --start-date "$START_DATE" \
  --full-sync
```

**Timeline**:
- 30k records × ~30 records/sec = ~17 minutos
- Sync Typesense: ~5 minutos
- **Total**: ~25 minutos

### Monitoramento

**Métricas PostgreSQL**:
```sql
-- Cobertura de embeddings para 2025
SELECT
  COUNT(*) FILTER (WHERE content_embedding IS NOT NULL) as with_embeddings,
  COUNT(*) as total,
  ROUND(COUNT(*) FILTER (WHERE content_embedding IS NOT NULL)::numeric / COUNT(*) * 100, 2) as coverage_pct
FROM news
WHERE published_at >= '2025-01-01' AND published_at < '2026-01-01';

-- Sync lag (PG vs Typesense)
SELECT COUNT(*) as pending_sync
FROM news
WHERE published_at >= '2025-01-01'
  AND content_embedding IS NOT NULL
  AND embedding_generated_at > (
    SELECT completed_at FROM sync_log
    WHERE operation = 'typesense_embeddings_sync'
      AND status = 'completed'
    ORDER BY completed_at DESC LIMIT 1
  );
```

**Alertas**:
- Embedding failure rate > 5%: WARNING
- Typesense sync failed: ERROR
- Embedding coverage < 90% para 2025: WARNING

### Rollback Plan

| Cenário | Impacto | Rollback |
|---------|---------|----------|
| **Embedding generation fails** | Baixo (NULL embeddings) | Re-run job após fix |
| **Typesense sync fails** | Médio (busca sem embeddings) | Re-run sync job |
| **Schema migration fails** | Alto (bloqueio) | Restore Cloud SQL backup |
| **Performance degradation** | Médio (queries lentas) | DROP HNSW index |

**Rollback emergencial**:
```yaml
# Disable jobs no workflow (comment out)
# generate-embeddings: ...
# sync-embeddings-to-typesense: ...
```

### Estimativas

**Esforço de Desenvolvimento**: ~53 horas (~7 dias)
- Database migrations: 4h
- EmbeddingGenerator: 8h
- TypesenseSyncManager: 8h
- CLI commands: 2h
- Testes (unit + integration): 10h
- Docker & dependencies: 3h
- Workflow GitHub Actions: 4h
- Terraform: 2h
- Documentação: 4h
- Code review: 8h

**Esforço de Deployment**: ~30 horas (~4 dias)
- Infrastructure setup: 4h
- Testes locais: 5h
- Backfill (2025): 2h (runtime: ~25 min)
- Typesense schema update: 3h
- Workflow integration: 2h
- Monitoring: 4h
- Observação (1 semana): 2h

**Total: ~4 semanas** (desenvolvimento + deployment + validação)

### Arquivos Críticos

**Novos**:
- `scripts/migrations/001_add_pgvector_extension.sql`
- `scripts/migrations/002_add_embedding_column.sql`
- `scripts/migrations/003_create_embedding_index.sql`
- `src/data_platform/jobs/embeddings/__init__.py`
- `src/data_platform/jobs/embeddings/embedding_generator.py`
- `src/data_platform/jobs/embeddings/typesense_sync.py`
- `scripts/backfill_embeddings.sh`
- `tests/unit/test_embedding_generator.py`
- `tests/unit/test_typesense_sync.py`
- `tests/integration/test_embedding_workflow.py`

**Modificados**:
- `.github/workflows/pipeline-steps.yaml` (adicionar 2 jobs)
- `src/data_platform/cli.py` (2 comandos)
- `src/data_platform/models/news.py` (campos embedding)
- `pyproject.toml` (ML dependencies)
- `Dockerfile` (pre-download modelo)
- `infra/terraform/cloud_sql.tf` (pgvector flag)
- `typesense/src/typesense_dgb/collection.py` (campo content_embedding)

### Critérios de Conclusão

- [ ] pgvector habilitado no Cloud SQL
- [ ] Embeddings gerados para todas notícias de 2025
- [ ] Cobertura de embeddings > 95% para 2025
- [ ] Typesense sincronizado com embeddings
- [ ] Pipeline diário funciona com 2 novos jobs
- [ ] Testes passam (unit + integration)
- [ ] Busca semântica funciona no Typesense MCP Server
- [ ] Documentação atualizada

---

## Fase 5: PostgreSQL como Primary

**Objetivo**: Trocar a fonte de verdade para PostgreSQL e criar sync para HuggingFace.

### Tarefas

- [ ] 5.1 Implementar HuggingFaceSyncJob
- [ ] 5.2 Criar workflow de sync (diário, após pipeline)
- [ ] 5.3 Alterar STORAGE_BACKEND=postgres
- [ ] 5.4 Alterar STORAGE_READ_FROM=postgres
- [ ] 5.5 Validar que HF continua sendo atualizado

### Sync Job

```bash
# Executado diariamente após o pipeline principal
python -m data_platform.jobs.hf_sync.sync_job --incremental
```

### Fluxo de Dados (Novo)

```
Scrapers
    ↓
PostgresManager.insert()
    ↓
PostgreSQL (SOURCE OF TRUTH)
    ↓
HuggingFaceSyncJob (diário)
    ↓
HuggingFace (DADOS ABERTOS)
```

### Critérios de Conclusão

- [ ] PostgreSQL é a fonte de verdade
- [ ] HuggingFace é atualizado diariamente
- [ ] Lag máximo de 24h entre PG e HF
- [ ] Pipeline funciona sem erros por 7+ dias
- [ ] Documentação atualizada (arquitetura, fluxo de dados)
- [ ] PR criado documentando progresso da fase

---

## Fase 6: Migração de Consumidores

**Objetivo**: Migrar sistemas downstream para ler do PostgreSQL.

### Tarefas

- [ ] 6.1 Atualizar Typesense loader para ler do PostgreSQL
- [ ] 6.2 Atualizar Qdrant indexer para ler do PostgreSQL
- [ ] 6.3 Atualizar MCP Server se necessário
- [ ] 6.4 Deprecar leitura direta do HuggingFace
- [ ] 6.5 Documentar nova arquitetura

### Ordem de Migração

1. **Typesense** (prioridade alta - usado pelo portal)
2. **Qdrant** (prioridade média - busca semântica)
3. **Streamlit apps** (prioridade baixa - uso interno)
4. **MCP Server** (prioridade baixa - já usa Typesense)

### Critérios de Conclusão

- [ ] Todos os consumidores migrados
- [ ] Nenhum sistema lê diretamente do HuggingFace
- [ ] Performance igual ou melhor
- [ ] Documentação completa atualizada (arquitetura final, guias de consumidores)
- [ ] PR criado documentando conclusão da migração

---

## Rollback Plan

### Por Fase

| Fase | Rollback |
|------|----------|
| 1-2 | Sem impacto, apenas desenvolvimento |
| 3 | Manter HF como está, ignorar PG |
| 4 | Mudar para STORAGE_BACKEND=huggingface |
| 5 | Reverter para dual-write, depois para HF |
| 6 | Reverter consumidores para HF |

### Comando de Rollback Emergencial

```bash
# Em caso de falha crítica
export STORAGE_BACKEND=huggingface
export STORAGE_READ_FROM=huggingface

# Redeploy dos serviços afetados
```

---

## Próximos Passos Imediatos

1. [ ] Revisar e aprovar este plano
2. [ ] Iniciar Fase 0 (setup do repositório)
3. [ ] Criar issue/milestone no GitHub para tracking

---

*Documento mantido em: `/destaquesgovbr/data-platform/_plan/README.md`*
