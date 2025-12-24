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
