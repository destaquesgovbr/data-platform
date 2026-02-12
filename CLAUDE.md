# DestaquesGovBr Data Platform

> **Status do Projeto**: Migração em andamento - HuggingFace Dataset → PostgreSQL
> **Fase Atual**: Fase 0 - Setup Inicial
> **Última Atualização**: 2024-12-24

---

## O Que É Este Projeto

**Data Platform** é o repositório centralizado para toda a infraestrutura de dados do DestaquesGovBr. Este projeto está em processo de migração do HuggingFace Dataset (usado como banco de dados) para PostgreSQL (Cloud SQL).

### DestaquesGovBr

Plataforma que agrega, enriquece e disponibiliza notícias de ~160 sites governamentais brasileiros (gov.br).

**Pipeline atual**:
```
Scrapers (Gov.br + EBC)
    ↓
HuggingFace Dataset (nitaibezerra/govbrnews)  ← Fonte de verdade ATUAL
    ↓
Enriquecimento IA (Cogfy) - temas + summaries
    ↓
Indexação (Typesense)
    ↓
Portal Web (Next.js)
```

**Pipeline alvo**:
```
Scrapers (Gov.br + EBC)
    ↓
PostgreSQL (Cloud SQL)  ← Nova fonte de verdade
    ↓
Sync diário → HuggingFace (dados abertos)
    ↓
Indexação (Typesense)
    ↓
Portal Web (Next.js)
```

---

## Estrutura do Repositório

```
data-platform/
├── _plan/                          # Documentação da migração
│   ├── README.md                   # Plano completo (6 fases)
│   ├── CONTEXT.md                  # Contexto técnico para LLMs
│   ├── CHECKLIST.md                # Verificações por fase
│   ├── DECISIONS.md                # ADRs (decisões arquiteturais)
│   ├── PROGRESS.md                 # Log de progresso
│   └── SCHEMA.md                   # Schema PostgreSQL
├── src/
│   └── data_platform/
│       ├── managers/               # Gerenciadores de storage
│       │   ├── postgres_manager.py
│       │   ├── dataset_manager.py  (migrado do scraper)
│       │   └── storage_adapter.py
│       ├── typesense/              # Módulo Typesense
│       │   ├── client.py           # Conexão com Typesense
│       │   ├── collection.py       # Schema da collection
│       │   ├── indexer.py          # Indexação de documentos
│       │   └── utils.py            # Utilitários
│       ├── jobs/                   # Jobs de processamento
│       │   ├── scraper/
│       │   ├── enrichment/
│       │   ├── typesense/          # Jobs de sincronização
│       │   │   ├── sync_job.py     # PG → Typesense
│       │   │   └── collection_ops.py
│       │   └── hf_sync/
│       ├── models/                 # Modelos Pydantic
│       └── dags/                   # DAGs Airflow (futuro)
├── tests/
│   ├── unit/
│   └── integration/
├── scripts/
│   ├── create_schema.py
│   ├── populate_agencies.py
│   ├── populate_themes.py
│   ├── migrate_hf_to_postgres.py
│   └── validate_migration.py
├── pyproject.toml
└── README.md
```

---

## Arquitetura de Dados

### Schema PostgreSQL

**Tabelas principais**:
- `agencies` - Dados mestres de agências governamentais (158 registros)
- `themes` - Taxonomia hierárquica de temas (3 níveis)
- `news` - Notícias (~300k registros)
- `sync_log` - Log de sincronizações

**Normalização**: Parcial
- `agencies` e `themes` normalizados
- `news` com FKs + campos denormalizados para performance (agency_key, agency_name)

Ver detalhes completos em [_plan/SCHEMA.md](_plan/SCHEMA.md).

### Estratégia de Migração

**6 Fases graduais**:

1. **Fase 0**: Setup do repositório ← VOCÊ ESTÁ AQUI
2. **Fase 1**: Infraestrutura (Cloud SQL, Terraform)
3. **Fase 2**: PostgresManager (código Python)
4. **Fase 3**: Migração de dados (HF → PG)
5. **Fase 4**: Dual-write (validação)
6. **Fase 5**: PostgreSQL como primary
7. **Fase 6**: Migração de consumidores

Ver plano completo em [_plan/README.md](_plan/README.md).

---

## Tecnologias

### Backend
- **Python 3.11+**
- **PostgreSQL 15** (Cloud SQL)
- **SQLAlchemy 2.0** + psycopg2

### Data Processing
- **Pandas** - manipulação de dados
- **HuggingFace Datasets** - interface com HF
- **PyArrow** - Parquet

### Quality
- **Pytest** - testes
- **Black** - formatação
- **Ruff** - linting
- **MyPy** - type checking

---

## Configuração

### Variáveis de Ambiente

```bash
# PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/govbrnews
STORAGE_BACKEND=huggingface  # huggingface | postgres | dual_write
STORAGE_READ_FROM=huggingface

# HuggingFace
HF_TOKEN=hf_xxx

# Cogfy (enriquecimento)
COGFY_API_KEY=xxx
COGFY_COLLECTION_ID=xxx
```

### Instalação

```bash
# Com Poetry
poetry install

# Com pip
pip install -e .

# Rodar testes
poetry run pytest
```

### Configuração de URLs do Scraper

O scraper usa `src/data_platform/scrapers/config/site_urls.yaml` para definir quais agências serão processadas.

**Formato**:

```yaml
# Agência ativa
mec:
  url: https://www.gov.br/mec/pt-br/assuntos/noticias
  active: true

# Agência desabilitada
cisc:
  url: https://www.gov.br/pt-br/noticias
  active: false
  disabled_reason: "URL generica, nao especifica da agencia"
  disabled_date: "2025-01-15"
```

**Campos**:
| Campo | Tipo | Obrigatório | Default | Descrição |
|-------|------|-------------|---------|-----------|
| `url` | string | Sim | - | URL da página de notícias |
| `active` | bool | Não | `true` | Se deve ser processada |
| `disabled_reason` | string | Não | - | Motivo da desativação |
| `disabled_date` | string | Não | - | Data da desativação (YYYY-MM-DD) |

---

## Typesense

O Typesense é usado como motor de busca para as notícias, oferecendo busca textual e semântica.

### Comandos CLI

```bash
# Sincronizar dados do PostgreSQL para Typesense
poetry run data-platform sync-typesense --start-date 2025-01-01

# Listar collections
poetry run data-platform typesense-list

# Deletar collection (com confirmação)
poetry run data-platform typesense-delete --confirm
```

### Variáveis de Ambiente

```bash
TYPESENSE_HOST=34.39.186.38
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=<sua-api-key>
```

### Workflows

| Workflow | Descrição |
|----------|-----------|
| `typesense-daily-load.yaml` | Carga incremental diária (7 dias) |
| `typesense-full-reload.yaml` | Recarga completa (manual) |
| `typesense-docker-build.yaml` | Build da imagem Docker |

### Documentação Detalhada

Ver [docs/typesense/](docs/typesense/) para documentação completa:
- [setup.md](docs/typesense/setup.md) - Configuração do servidor
- [development.md](docs/typesense/development.md) - Desenvolvimento local
- [data-management.md](docs/typesense/data-management.md) - Gerenciamento de dados

---

## Cloud Composer (Airflow)

O Cloud Composer é usado para orquestrar DAGs que sincronizam dados entre PostgreSQL e HuggingFace.

### DAGs

| DAG | Schedule | Descrição |
|-----|----------|-----------|
| `sync_postgres_to_huggingface` | 6 AM UTC | Sincroniza notícias do dia anterior para HuggingFace |
| `test_postgres_connection` | Manual | Testa conectividade com PostgreSQL |

### Workflows

| Workflow | Descrição |
|----------|-----------|
| `composer-deploy-dags.yaml` | Deploy de DAGs para o Composer |
| `composer-health-check.yaml` | Verifica saúde do Composer (a cada 6h) |

### Deploy de DAGs

```bash
# Disparar deploy manualmente
gh workflow run composer-deploy-dags.yaml
```

O deploy também é disparado automaticamente quando:
1. Arquivos em `src/data_platform/dags/` são modificados
2. O Composer é modificado via Terraform (cross-repo dispatch)

### Resiliência

O Composer possui proteções contra perda de DAGs:

1. **Prevenção**: `prevent_destroy=true` no Terraform impede destruição acidental
2. **Validação**: CI/CD bloqueia planos que tentam recriar o Composer
3. **Auto-Recovery**: Health check a cada 6h dispara deploy se bucket estiver vazio
4. **Cross-Repo Trigger**: Mudanças no Composer disparam deploy automático

### Troubleshooting

Se as DAGs sumirem do Airflow:

```bash
# 1. Verificar bucket atual
gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="value(config.dagGcsPrefix)"

# 2. Disparar redeploy
gh workflow run composer-deploy-dags.yaml
```

Ver [docs/runbooks/composer-recovery.md](docs/runbooks/composer-recovery.md) para runbook completo.

---

## Desenvolvimento

### Padrões de Código

```python
# Type hints obrigatórios
def insert(self, data: OrderedDict, allow_update: bool = False) -> int:
    """
    Insere registros no banco.

    Args:
        data: Dados a inserir
        allow_update: Se True, atualiza registros existentes

    Returns:
        Número de registros inseridos/atualizados
    """
    ...

# Sempre usar context managers para conexões
with self.get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute(query, params)
```

### Testes

```bash
# Rodar todos os testes
pytest

# Com cobertura
pytest --cov=data_platform

# Apenas unitários
pytest tests/unit/

# Apenas integração
pytest tests/integration/
```

---

## Repositórios Relacionados

| Repositório | Caminho | Descrição |
|-------------|---------|-----------|
| **data-platform** | `/destaquesgovbr/data-platform` | Este repo (código Python) |
| **infra** | `/destaquesgovbr/infra` | Terraform (privado) |
| **scraper** | `/destaquesgovbr/scraper` | Scrapers atuais (será migrado) |
| **portal** | `/destaquesgovbr/portal` | Frontend Next.js |
| **typesense** | `/destaquesgovbr/typesense` | ~~Loader do Typesense~~ (migrado para data-platform) |
| **agencies** | `/destaquesgovbr/agencies` | agencies.yaml |
| **themes** | `/destaquesgovbr/themes` | themes_tree.yaml |

---

## Decisões Arquiteturais

Ver todas as ADRs em [_plan/DECISIONS.md](_plan/DECISIONS.md).

**Principais**:
- ADR-001: PostgreSQL como BD principal
- ADR-002: Sync diário com HuggingFace
- ADR-003: Schema parcialmente normalizado
- ADR-004: Arquitetura híbrida de repos (código público, infra privado)
- ADR-005: Migração gradual com dual-write

---

## Como Contribuir

### Para LLMs (Claude, GPT, etc)

1. **Sempre leia primeiro**: [_plan/CONTEXT.md](_plan/CONTEXT.md)
2. **Verifique progresso**: [_plan/PROGRESS.md](_plan/PROGRESS.md)
3. **Consulte decisões**: [_plan/DECISIONS.md](_plan/DECISIONS.md)
4. **Siga checklist**: [_plan/CHECKLIST.md](_plan/CHECKLIST.md)
5. **Atualize PROGRESS.md** ao completar tarefas

### Para Humanos

1. Leia o [plano completo](_plan/README.md)
2. Verifique a fase atual em [PROGRESS.md](_plan/PROGRESS.md)
3. Pegue uma tarefa do [CHECKLIST.md](_plan/CHECKLIST.md)
4. Implemente seguindo os padrões
5. Adicione testes
6. Atualize PROGRESS.md

---

## Recursos Externos

### Dados

- **HuggingFace Dataset**: https://huggingface.co/datasets/nitaibezerra/govbrnews
- **Dataset Reduzido**: https://huggingface.co/datasets/nitaibezerra/govbrnews-reduced

### Infraestrutura

- **Cloud SQL**: `govbrnews-postgres` (us-east1)
- **Portal**: Cloud Run (destaquesgovbr-portal)
- **Typesense**: Compute Engine (typesense-server)

### Documentação

- Documentação geral: `/Users/nitai/Dropbox/dev-mgi/docs/`
- Plano de migração: `./_plan/`

---

## Fase Atual: Fase 0 - Setup Inicial

### Objetivos

- [x] Criar estrutura de diretórios
- [x] Configurar pyproject.toml
- [x] Criar CLAUDE.md (este arquivo)
- [ ] Inicializar git
- [ ] Criar .gitignore
- [ ] Criar README.md principal
- [ ] Criar testes básicos

### Próximos Passos

Após completar a Fase 0, iniciar **Fase 1: Infraestrutura**.

Ver [_plan/README.md](_plan/README.md#fase-1-infraestrutura) para detalhes.

---

## Contato

- **Projeto**: DestaquesGovBr
- **Repositório**: destaquesgovbr/data-platform
- **Documentação**: `./_plan/`

---

*Este documento é mantido manualmente. Atualize conforme o projeto evolui.*
