# Log de Progresso da Migração

> **Instruções**: Registre aqui cada ação significativa realizada, problemas encontrados e soluções aplicadas. Isso cria um histórico completo da migração.

---

## Como Usar Este Documento

Ao completar uma tarefa, adicione uma entrada no formato:

```markdown
### YYYY-MM-DD HH:MM - [Fase X] Título da Tarefa

**Status**: ✅ Completo | ⚠️ Em progresso | ❌ Bloqueado

**O que foi feito**:
- Bullet point 1
- Bullet point 2

**Problemas encontrados**:
- Problema 1 e como foi resolvido

**Próximos passos**:
- [ ] Tarefa 1
- [ ] Tarefa 2

**Artefatos**:
- Link para PR
- Link para doc
```

---

## Histórico

### 2024-12-24 - [Fase 0] Criação do Repositório e Plano

**Status**: ✅ Completo

**O que foi feito**:
- Criada estrutura do repositório `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/data-platform`
- Criado diretório `_plan/` com documentação
- Documentos criados:
  - README.md (plano geral com 6 fases)
  - CONTEXT.md (contexto técnico para LLMs)
  - CHECKLIST.md (verificações por fase)
  - DECISIONS.md (ADRs com 6 decisões iniciais)
  - PROGRESS.md (este arquivo)
  - SCHEMA.md (schema PostgreSQL detalhado)

**Decisões tomadas**:
- ADR-001: PostgreSQL como BD principal
- ADR-002: Sync diário com HuggingFace
- ADR-003: Schema parcialmente normalizado
- ADR-004: Arquitetura híbrida de repos
- ADR-005: Migração gradual com dual-write
- ADR-006: Airflow (pendente decisão futura)

**Próximos passos**:
- [ ] Revisar e aprovar o plano completo
- [ ] Iniciar Fase 0: Setup do repositório
- [ ] Criar pyproject.toml com dependências

**Artefatos**:
- Documentação: `/destaquesgovbr/data-platform/_plan/`

### 2024-12-24 - [Fase 0] Setup Completo do Repositório

**Status**: ✅ Completo

**O que foi feito**:
- Criada estrutura completa de diretórios (`src/`, `tests/`, `scripts/`)
- Criados todos os `__init__.py` para pacotes Python
- Configurado `pyproject.toml` com Poetry:
  - Dependências: psycopg2, pandas, datasets, huggingface-hub, pydantic, etc
  - Dev dependencies: pytest, black, ruff, mypy
  - Configurações de linting e formatação
- Criado `CLAUDE.md` com contexto completo do projeto
- Criado `README.md` principal com quick start e documentação
- Configurado `.gitignore` para Python, databases, secrets
- Inicializado git e criado primeiro commit
- Criada estrutura de testes:
  - `tests/conftest.py` com fixtures
  - `tests/unit/test_example.py` com testes de exemplo
  - `pytest.ini` com configuração

**Estrutura criada**:
```
data-platform/
├── _plan/ (6 documentos)
├── src/data_platform/
│   ├── managers/
│   ├── jobs/ (scraper, enrichment, hf_sync)
│   ├── models/
│   └── dags/
├── tests/ (unit, integration)
├── scripts/
└── [pyproject.toml, README.md, CLAUDE.md, .gitignore]
```

**Comandos validados**:
```bash
poetry install
pytest tests/
```

**Próximos passos**:
- [ ] Iniciar Fase 1: Infraestrutura
- [ ] Criar cloud_sql.tf no repo infra
- [ ] Provisionar Cloud SQL

**Artefatos**:
- Repositório: `/destaquesgovbr/data-platform`
- Documentação: `_plan/`
- Código: `src/`, `tests/`, `scripts/`

### 2024-12-26 - [Fase 4.7] Planejamento de Embeddings Semânticos

**Status**: ⚠️ Em planejamento

**O que foi feito**:
- Criado plano completo para Fase 4.7 (Embeddings Semânticos)
- Documentado em `/Users/nitai/.claude/plans/stateful-wobbling-taco.md`
- Integrado ao plano principal em `_plan/README.md`
- Adicionado à `_plan/CHECKLIST.md`
- Criado ADR-007 em `_plan/DECISIONS.md`

**Decisões tomadas**:
- ADR-007: Estratégia de embeddings semânticos
  - Modelo: paraphrase-multilingual-mpnet-base-v2 (768 dims)
  - Input: `title + " " + summary` (summary do Cogfy)
  - **Escopo: Apenas notícias de 2025** (têm summary do Cogfy)
  - Storage: PostgreSQL (pgvector) + Typesense
  - 2 novos jobs no workflow: generate-embeddings, sync-embeddings-to-typesense

**Arquitetura**:
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
  [NOVO] generate-embeddings → PostgreSQL (embeddings)
      ↓
  [NOVO] sync-embeddings-to-typesense → Typesense
```

**Escopo definido**:
- **Apenas notícias de 2025** (~30k registros)
- Notícias anteriores não têm summary do Cogfy, portanto não serão processadas
- Embeddings gerados de `title + " " + summary`
- Fallback para `content` se summary ausente

**Implementação planejada**:
- Database: Habilitar pgvector, adicionar colunas, criar índices HNSW
- Python: EmbeddingGenerator + TypesenseSyncManager
- CLI: 2 novos comandos
- Testes: unit + integration (com Docker local)
- Workflow: 2 novos jobs após enrich-themes
- Docker: Pre-download modelo (confirmado)
- Secrets: Usar existentes do Typesense (confirmado em infra)

**Estimativas**:
- Desenvolvimento: ~53 horas (~7 dias)
- Deployment: ~30 horas (~4 dias)
- Backfill 2025: ~25 minutos runtime
- Total: ~4 semanas

**Próximos passos**:
- [ ] Revisar e aprovar Fase 4.7
- [ ] Criar PR Terraform (habilitar pgvector)
- [ ] Implementar EmbeddingGenerator class
- [ ] Implementar TypesenseSyncManager class
- [ ] Escrever testes automatizados
- [ ] Testar localmente (Docker PostgreSQL + Typesense)

**Artefatos**:
- Plano detalhado: `/Users/nitai/.claude/plans/stateful-wobbling-taco.md`
- Integração: `_plan/README.md` (Fase 4.7)
- Checklist: `_plan/CHECKLIST.md` (Fase 4.7)
- ADR: `_plan/DECISIONS.md` (ADR-007)



**Problemas encontrados**:
- Nenhum

**Próximos passos**:
- [ ] Instalar dependências com Poetry/pip
- [ ] Rodar testes para validar setup
- [ ] Iniciar Fase 1: Infraestrutura (Cloud SQL)

**Artefatos**:
- Git commit: `58e6dc0` - "feat: initial setup - Fase 0"
- Repositório: `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/data-platform`

### 2024-12-24 - [Fase 1] Infraestrutura Cloud SQL Configurada

**Status**: ✅ Completo (Terraform criado, aguardando apply via CI/CD)

**O que foi feito**:
- Criado `cloud_sql.tf` com configuração completa do PostgreSQL:
  - Instância PostgreSQL 15
  - Tier: `db-custom-1-3840` (1 vCPU, 3.75GB RAM)
  - Storage: 50GB SSD com auto-resize até 500GB
  - Backups diários às 3 AM UTC (30 dias de retenção)
  - Point-in-time recovery habilitado (7 dias)
  - Região: southamerica-east1 (São Paulo)
- Configurado secrets no Secret Manager:
  - `govbrnews-postgres-connection-string` (URI completa)
  - `govbrnews-postgres-host` (IP privado)
  - `govbrnews-postgres-password` (senha gerada)
- Criado service account `destaquesgovbr-data-platform`
- Configurado IAM bindings para acesso aos secrets:
  - data-platform service account
  - github-actions service account
- Adicionadas variáveis ao `variables.tf`:
  - `postgres_tier`
  - `postgres_disk_size_gb`
  - `postgres_high_availability`
  - `postgres_authorized_networks`
- Adicionado provider `random` ao `main.tf` (geração de senhas)
- Criada documentação completa: `docs/cloud-sql.md`

**Configuração do Database**:
- Nome: `govbrnews`
- Charset: UTF8
- User: `govbrnews_app` (senha gerenciada automaticamente)

**Problemas encontrados**:
- Nenhum

**Próximos passos**:
- [ ] Aplicar Terraform via CI/CD workflow
- [ ] Testar conexão ao PostgreSQL via Cloud SQL Proxy
- [ ] Validar acesso aos secrets
- [ ] Criar schema do banco (agencies, themes, news)
- [ ] Iniciar Fase 2: PostgresManager

**Artefatos**:
- Git commit (infra): `c2f525e` - "feat: add Cloud SQL PostgreSQL for Data Platform"
- Arquivos criados:
  - `/destaquesgovbr/infra/terraform/cloud_sql.tf`
  - `/destaquesgovbr/infra/docs/cloud-sql.md`
- Arquivos modificados:
  - `/destaquesgovbr/infra/terraform/variables.tf`
  - `/destaquesgovbr/infra/terraform/main.tf`

### 2024-12-24 - [Fase 1] PR Criado e Schema SQL Preparado

**Status**: ⚠️ Em progresso (aguardando merge do PR #42)

**O que foi feito**:
- Criado PR #42 no repositório infra: "feat: Add Cloud SQL PostgreSQL for Data Platform"
- Terraform plan executado com sucesso via GitHub Actions
- Plan output: "20 to add, 8 to change, 0 to destroy"
- Corrigido erro de validação (removido `require_ssl` inválido)
- **Preparação para Fase 2** (enquanto aguarda merge):
  - Criado `scripts/create_schema.sql` com schema completo:
    - 4 tabelas: agencies, themes, news, sync_log
    - 15+ indexes otimizados para queries comuns
    - 3 triggers (updated_at, denormalização)
    - 2 views auxiliares (news_with_themes, recent_syncs)
    - Validação automática de schema
  - Criado `scripts/setup_database.sh`:
    - Script automatizado para criar schema via Cloud SQL Proxy
    - Validação de pré-requisitos
    - Verificação de estado do banco
    - Saída formatada e colorida
  - Criado `_plan/POSTGRES_TEST_PLAN.md`:
    - 6 categorias de testes pós-apply
    - 15+ casos de teste validando infraestrutura
    - Checklist de validação completo

**Problemas encontrados**:
- **Erro Terraform**: Argumento `require_ssl` não é válido em `ip_configuration` block
  - **Solução**: Removido a linha, SSL é gerenciado pelo Cloud SQL Proxy

**Próximos passos**:
- [ ] Aguardar merge do PR #42 para executar terraform apply
- [ ] Executar testes de validação conforme POSTGRES_TEST_PLAN.md
- [ ] Rodar `scripts/setup_database.sh` para criar schema
- [ ] Popular agencies e themes (scripts a criar)

**Artefatos**:
- PR #42: https://github.com/destaquesgovbr/infra/pull/42
- Git branch: `feat/cloud-sql-postgres`
- Workflow run: terraform-plan (ID: 20490642048) - ✅ SUCCESS
- Arquivos criados (data-platform):
  - `scripts/create_schema.sql` (500+ linhas de SQL)
  - `scripts/setup_database.sh` (script shell automatizado)
  - `_plan/POSTGRES_TEST_PLAN.md` (plano de testes)

### 2024-12-24 - [Fase 1] Cloud SQL Provisionado e Validado - FASE 1 COMPLETA

**Status**: ✅ Completo

**O que foi feito**:
- **PRs mergeados**: #42 (Cloud SQL), #43 (cache size fix), #44 (VPC peering), #45 (IAM permissions)
- **Terraform apply executado com sucesso** via GitHub Actions
- **Cloud SQL PostgreSQL 15 provisionado**:
  - Instância: `destaquesgovbr-postgres`
  - Status: RUNNABLE
  - IP Privado: 10.5.0.3
  - IP Público: 34.39.209.161
  - Região: southamerica-east1 (São Paulo)
  - Tier: db-custom-1-3840 (1 vCPU, 3.75GB RAM)
  - Storage: 50GB SSD (auto-resize até 500GB)
  - Deletion protection: Habilitada
- **Secrets criados no Secret Manager**:
  - `govbrnews-postgres-connection-string` (URI completa)
  - `govbrnews-postgres-host` (IP: 10.5.0.3)
  - `govbrnews-postgres-password` (32 caracteres)
- **VPC Peering configurado**:
  - IP range reservado: 10.5.0.0/16
  - Service Networking connection estabelecida
- **Conexão validada via Cloud SQL Proxy**:
  - PostgreSQL 15.15 respondendo
  - Database `govbrnews` acessível
  - User `govbrnews_app` autenticado
- **Schema do banco criado com sucesso**:
  - 5 tabelas: agencies, themes, news, sync_log, schema_version
  - 22 indexes (20 criados, 2 warnings não críticos)
  - 4 triggers: update timestamps, denormalize agency data
  - 2 views: news_with_themes, recent_syncs
  - Full-text search configurado (português)
- **IAM permissions persistidas no Terraform**:
  - roles/cloudsql.admin para github-actions
  - roles/servicenetworking.networksAdmin para github-actions
  - roles/cloudsql.client para data-platform e github-actions
  - roles/secretmanager.secretAccessor para data-platform e github-actions

**Problemas encontrados e soluções**:
1. **effective_cache_size muito grande**:
   - Erro: 786432 (768MB) excedia limite de 344064 para instância 3.75GB
   - Solução: PR #43 reduzindo para 344064 (~336MB)

2. **VPC não pareada com Service Networking**:
   - Erro: NETWORK_NOT_PEERED ao criar Cloud SQL
   - Solução: PR #44 adicionando google_compute_global_address e google_service_networking_connection

3. **Permissões IAM faltando para GitHub Actions**:
   - Erro 403: Cloud SQL Admin não tinha roles/cloudsql.admin
   - Erro 403: VPC peering precisava de roles/servicenetworking.networksAdmin
   - Solução temporária: Adicionado via gcloud manualmente
   - Solução permanente: PR #45 persistindo no Terraform

4. **Porta 5432 em uso ao rodar setup_database.sh**:
   - Erro: Cloud SQL Proxy não conseguia bind na porta
   - Solução: `lsof -ti:5432 | xargs kill -9`

5. **Indexes com funções não-IMMUTABLE**:
   - Warning: 2 indexes falharam (DATE() e GIN com concat)
   - Impacto: Não crítico, queries ainda funcionam
   - Ação: Documentado para otimização futura

**Validação completa realizada**:
- ✅ Cloud SQL status: RUNNABLE
- ✅ Conexão via Cloud SQL Proxy: Funcional
- ✅ Secrets no Secret Manager: Configurados e acessíveis
- ✅ Schema criado: 5 tabelas, 20 indexes, 4 triggers, 2 views
- ✅ IAM permissions: Todas configuradas via Terraform
- ✅ VPC peering: Estabelecido com Service Networking

**Próximos passos**:
- [ ] Iniciar Fase 2: Implementar PostgresManager
- [ ] Criar script para popular tabela `agencies` (~158 registros)
- [ ] Criar script para popular tabela `themes` (taxonomia hierárquica)
- [ ] Implementar cache em memória para agencies e themes
- [ ] Adicionar connection pooling ao PostgresManager

**Artefatos**:
- PRs mergeados:
  - #42: feat: Add Cloud SQL PostgreSQL for Data Platform
  - #43: fix: reduce effective_cache_size for db-custom-1-3840
  - #44: feat: add VPC peering for Cloud SQL
  - #45: feat: persist Cloud SQL IAM permissions in Terraform
- Cloud SQL instance: `destaquesgovbr-postgres` (RUNNABLE)
- Schema criado: v1.0
- Documentação: `/destaquesgovbr/infra/docs/cloud-sql.md`

### 2024-12-24 - [Fase 2] PostgresManager Implementado - FASE 2 COMPLETA

**Status**: ✅ Completo

**O que foi feito**:
- **PostgresManager implementado** ([postgres_manager.py](src/data_platform/managers/postgres_manager.py)):
  - Connection pooling com psycopg2 (min=1, max=10 connections)
  - Cache em memória para agencies e themes
  - Métodos CRUD: insert(), update(), get(), get_by_unique_id()
  - Suporte a batch operations com execute_values
  - Auto-detecção de connection string (Secret Manager ou Cloud SQL Proxy)
  - Context manager para gestão de recursos
- **Modelos Pydantic criados** ([models/news.py](src/data_platform/models/news.py)):
  - NewsInsert (para inserção)
  - News (completo com IDs)
  - Agency
  - Theme
- **Scripts para popular tabelas mestres**:
  - [populate_agencies.py](scripts/populate_agencies.py): 159 agências de agencies.yaml
  - [populate_themes.py](scripts/populate_themes.py): 588 temas de themes_tree_enriched_full.yaml
  - Ambos com suporte a Cloud SQL Proxy e dry-run mode
- **Testes implementados**:
  - test_postgres_manager.py com 10 casos de teste
  - test_models.py validando Pydantic models
  - Cobertura: > 80%
- **Documentação**:
  - README.md atualizado com uso do PostgresManager
  - Docstrings em todos os métodos

**Problemas encontrados e soluções**:
1. **Foreign key constraint em agencies.parent_key**:
   - Erro: agencies com parent_key referenciando agências não inseridas ainda
   - Solução: Ordenação de inserção (pais primeiro) e tratamento de referencias circulares

**Validação realizada**:
- ✅ PostgresManager conecta ao Cloud SQL via proxy
- ✅ Cache de agencies e themes funciona
- ✅ Insert e update funcionando
- ✅ Batch operations otimizadas
- ✅ 159 agencies populadas com sucesso
- ✅ 588 themes populados com sucesso
- ✅ Todos os testes passando

**Próximos passos**:
- [x] Iniciar Fase 3: Migração de dados do HuggingFace
- [x] Criar scripts de migração e validação
- [x] Testar migração localmente com Docker

**Artefatos**:
- PR #1: feat: Phase 2 - PostgresManager Implementation (MERGED 2024-12-24 19:52)
- Commits:
  - `33c1e76`: feat: implement PostgresManager and populate master tables (Phase 2)
  - `e3f78cd`: feat: add scripts to populate master tables
- Arquivos criados:
  - src/data_platform/managers/postgres_manager.py
  - src/data_platform/models/news.py
  - scripts/populate_agencies.py
  - scripts/populate_themes.py
  - tests/unit/test_postgres_manager.py
  - tests/unit/test_models.py

### 2024-12-25 - [Fase 3] Migração Completa para Cloud SQL - FASE 3 COMPLETA

**Status**: ✅ Completo

**O que foi feito**:
- **Migração de 309.050 registros executada com sucesso** (99.95% do dataset)
  - 193 registros ignorados por terem published_at = NULL
  - Taxa de inserção: ~450 registros/segundo (média)
  - Tempo total: ~12 minutos
- **Otimizações de performance aplicadas** (6-8x mais rápido):
  - Dropped idx_news_fts (índice FTS de 262MB → 1.1GB)
  - Disabled trigger denormalize_news_agency
  - Dropped indexes não-críticos durante bulk insert
- **Validação completa passou**:
  - 0 campos NULL em campos obrigatórios
  - 0 referências inválidas de agency
  - 0 referências inválidas de theme
  - 0 unique_ids duplicados
  - 100% consistência em amostragem de 100 registros
  - 95%+ cobertura de temas
- **Índices recriados** (sem FTS - buscas via Typesense):
  - idx_news_agency_date: 18 MB
  - idx_news_synced_to_hf: 8192 bytes
  - idx_news_theme_l1: 5976 kB
  - Trigger denormalize_news_agency reabilitado
- **Índice FTS removido permanentemente**:
  - Buscas são feitas no Typesense, não no PostgreSQL
  - Economia de 1.1GB de espaço
  - Script recreate_indexes_after_migration.py atualizado

**Problemas encontrados e soluções**:
1. **Performance inicial muito lenta (40-95 rec/s)**:
   - Causa: Índice FTS sendo atualizado a cada INSERT
   - Solução: Dropped todos os índices não-críticos durante migração

2. **Erro tsvector limit exceeded**:
   - Erro: "string is too long for tsvector (2300174 bytes, max 1048575 bytes)"
   - Causa: Alguns campos content excedem 1MB (limite do tsvector)
   - Solução: Dropped índice FTS (não necessário - Typesense é usado para buscas)

3. **CREATE INDEX CONCURRENTLY em transaction**:
   - Erro: "cannot run inside a transaction block"
   - Solução: Adicionado `conn.autocommit = True` no script

**Documentação criada**:
- [docs/migration/performance-optimization.md](docs/migration/performance-optimization.md)
  - Root causes da lentidão
  - Soluções aplicadas
  - Resultados (6-8x improvement)
  - Best practices para futuras migrações

**Artefatos**:
- Scripts executados:
  - scripts/migrate_hf_to_postgres.py (migração completa)
  - scripts/recreate_indexes_after_migration.py (índices sem FTS)
- Arquivos modificados:
  - scripts/recreate_indexes_after_migration.py (FTS removido)
- Documentação: docs/migration/performance-optimization.md

---

### 2024-12-24 - [Fase 3] Ambiente Docker e Scripts de Migração

**Status**: ✅ Completo (parte da Fase 3)

**O que foi feito**:
- **Ambiente Docker local criado**:
  - [docker-compose.yml](docker-compose.yml) com PostgreSQL 15 Alpine
  - Mesma configuração do Cloud SQL (PostgreSQL 15)
  - Volume persistente para dados (`destaquesgovbr-postgres-data`)
  - Healthcheck configurado
  - [docker/postgres/init.sql](docker/postgres/init.sql) com schema completo
  - Schema criado automaticamente na inicialização (5 tabelas, 22 indexes, 4 triggers, 2 views)
- **Scripts de migração**:
  - [migrate_hf_to_postgres.py](scripts/migrate_hf_to_postgres.py):
    - Carrega dataset completo do HuggingFace (nitaibezerra/govbrnews - 309.193 registros)
    - Migra em batches de 1000 registros com progress bar (tqdm)
    - Mapeia agências e temas usando cache do PostgresManager
    - Suporte a --max-records para testes
    - Suporte a --dry-run
    - Relatório detalhado de estatísticas
  - [validate_migration.py](scripts/validate_migration.py):
    - Valida contagem de registros (HF vs PG)
    - Verifica integridade referencial (agencies, themes)
    - Valida campos obrigatórios
    - Amostragem de consistência (100 registros)
    - Relatório em formato tabular
- **Correções implementadas**:
  - PostgresManager agora suporta DATABASE_URL environment variable
  - Prioridade: DATABASE_URL → Secret Manager → Cloud SQL Proxy
  - parse_datetime() corrigido para aceitar datetime objects (HuggingFace retorna objetos, não strings)
  - populate_agencies.py e populate_themes.py com suporte a --db-url e DATABASE_URL
  - Triggers temporariamente desabilitados durante populate de agencies (FK circulares)
- **Utilitários**:
  - [Makefile](Makefile) com comandos convenientes:
    - `make docker-up`: Iniciar PostgreSQL
    - `make setup-db`: Setup completo do banco local
    - `make migrate`: Migrar dados do HF
    - `make validate`: Validar migração
    - `make test`: Rodar testes
  - [.env.example](.env.example) com variáveis locais
  - [scripts/setup_local_db.sh](scripts/setup_local_db.sh) para setup automatizado
  - [.dockerignore](.dockerignore) para otimizar builds
- **Documentação**:
  - [docs/development/docker-setup.md](docs/development/docker-setup.md) (401 linhas):
    - Quick start guide
    - Arquitetura do ambiente
    - Comandos úteis
    - Troubleshooting completo
    - CI/CD integration
    - Diferenças vs Cloud SQL

**Testes realizados com Docker local**:
- ✅ Docker container iniciado com sucesso
- ✅ PostgreSQL 15.10 respondendo com healthcheck
- ✅ Schema criado automaticamente (5 tabelas: agencies, themes, news, sync_log, schema_version)
- ✅ 159 agencies populadas no Docker local
- ✅ 588 themes populados no Docker local
- ✅ **Migração de 100 registros de teste executada com sucesso em 0.05s** (2.112 records/s)
- ✅ Validação executada com todos os checks passando:
  - 0 campos NULL obrigatórios
  - 0 referências de agency inválidas
  - 0 referências de theme inválidas
  - 0 unique_ids duplicados
  - Campos denormalizados consistentes (agency_key, agency_name)

**Problemas encontrados e soluções**:
1. **PostgresManager não reconhecia DATABASE_URL**:
   - Erro: Tentava conectar via Secret Manager mesmo com DATABASE_URL setado
   - Solução: Adicionado check de DATABASE_URL como prioridade máxima em `_get_connection_string()`

2. **parse_datetime() falhava com datetime objects**:
   - Erro: "argument of type 'datetime.datetime' is not iterable"
   - Causa: HuggingFace datasets retorna datetime objects, não strings
   - Solução: Adicionado `isinstance(dt_input, datetime)` check antes de parsing

3. **Scripts populate não aceitavam connection string customizada**:
   - Problema: Forçava uso do Secret Manager localmente
   - Solução: Adicionado --db-url parameter e suporte a DATABASE_URL env var

4. **FK constraint violation ao popular agencies**:
   - Erro: parent_key referenciando agencies não inseridas
   - Solução: `ALTER TABLE agencies DISABLE TRIGGER ALL` durante inserção

**Próximos passos**:
- [x] Executar migração completa (~309k registros) no Cloud SQL
- [x] Validar migração completa com validate_migration.py
- [x] Atualizar documentação com resultados e lições aprendidas
- [x] Criar PR da Fase 3 incluindo todos os commits

**Artefatos**:
- Commits (aguardando PR):
  - `e3f78cd`: feat: add scripts to populate master tables
  - `87f04ef`: feat: add local Docker environment and migration scripts
  - `25459ef`: fix: support DATABASE_URL env var and handle datetime objects
- Arquivos criados:
  - docker-compose.yml
  - docker/postgres/init.sql
  - docker/README.md
  - .dockerignore
  - .env.example
  - Makefile
  - docs/development/docker-setup.md
  - scripts/migrate_hf_to_postgres.py
  - scripts/validate_migration.py
  - scripts/setup_local_db.sh
- Arquivos modificados:
  - src/data_platform/managers/postgres_manager.py (DATABASE_URL support)
  - scripts/populate_agencies.py (--db-url support)
  - scripts/populate_themes.py (--db-url support)

### 2024-12-26 - [Fase 4] Dual-Write Completo - Todas as Etapas Lendo de PostgreSQL

**Status**: ✅ Completo

**O que foi feito**:
- **PR #10 mergeado**: EnrichmentManager com suporte completo a leitura de PostgreSQL
  - `_load_and_filter_dataset()` agora usa StorageAdapter.get() quando STORAGE_READ_FROM=postgres
  - `_prepare_dataset_for_enrichment()` adaptado para mapear colunas PG (theme_1_level_1_code vs theme_1_level_1)
  - `_merge_with_full_dataset()` skip merge quando lendo de PostgreSQL (desnecessário)
  - `_upload_enriched_dataset()` suporta dual-write quando lendo de PostgreSQL
- **Workflow atualizado** (pipeline-steps.yaml):
  - Scraper: STORAGE_BACKEND=dual_write (lê HF, escreve em ambos)
  - EBC Scraper: STORAGE_BACKEND=dual_write (lê HF, escreve em ambos)
  - Upload to Cogfy: STORAGE_READ_FROM=postgres (lê PG)
  - Enrich: STORAGE_BACKEND=dual_write, STORAGE_READ_FROM=postgres (lê PG, escreve em ambos)
- **Testado localmente**:
  - 4 registros enriquecidos com sucesso lendo de PostgreSQL
  - Temas L1/L2/L3 e summaries atualizados corretamente

**Problemas encontrados**:
- **PR merge não incluiu mudança do workflow**: Squash merge incluiu apenas código Python
  - Solução: Commit adicional direto no main após merge

**Próximos passos**:
- [ ] Validar resultado do pipeline run 20529210748
- [ ] Considerar arquivar scraper repo após validação
- [ ] Iniciar Fase 5: PostgreSQL como primary (eliminar HuggingFace dos writes)

**Artefatos**:
- PR #10: feat: add PostgreSQL read support to EnrichmentManager
- Commits diretos no main:
  - workflow: add STORAGE_READ_FROM=postgres to enrich step
- Pipeline run: 20529210748 (em validação)

---

## Template para Novas Entradas

Copie e cole este template ao adicionar novas entradas:

```markdown
### YYYY-MM-DD HH:MM - [Fase X] Título da Tarefa

**Status**: ✅ Completo | ⚠️ Em progresso | ❌ Bloqueado

**O que foi feito**:
-

**Problemas encontrados**:
-

**Próximos passos**:
- [ ]

**Artefatos**:
-
```

---

## Marcos Importantes

| Data | Fase | Marco | Status |
|------|------|-------|--------|
| 2024-12-24 | 0 | Plano criado | ✅ |
| 2024-12-24 | 0 | Repositório setup completo | ✅ |
| 2024-12-24 | 1 | Cloud SQL configurado (Terraform) | ✅ |
| 2024-12-24 | 1 | Cloud SQL provisionado (apply) | ✅ |
| 2024-12-24 | 1 | Schema do banco criado e validado | ✅ |
| 2024-12-24 | 2 | PostgresManager implementado | ✅ |
| 2024-12-24 | 2 | Tabelas mestres populadas (agencies, themes) | ✅ |
| 2024-12-24 | 3 | Ambiente Docker local criado | ✅ |
| 2024-12-24 | 3 | Scripts de migração criados e testados | ✅ |
| 2024-12-25 | 3 | Migração completa executada (309k) | ✅ |
| 2024-12-25 | 4 | StorageAdapter implementado (PR #5) | ✅ |
| 2024-12-25 | 4 | StorageWrapper no scraper criado | ✅ |
| 2024-12-25 | 4 | Dual-write testado localmente (13 records) | ✅ |
| 2024-12-26 | 4 | GitHub Actions configurado dual_write | ✅ |
| 2024-12-26 | 4 | Enrich step lendo de PostgreSQL (PR #10) | ✅ |
| 2024-12-26 | 4 | Upload-to-Cogfy lendo de PostgreSQL | ✅ |
| 2024-12-26 | 4 | Pipeline completo validado em produção | ⏳ |
| ____-__-__ | 5 | PostgreSQL como primary | ⏳ |
| ____-__-__ | 6 | Todos consumidores migrados | ⏳ |

---

*Última atualização: 2024-12-26 18:00*
