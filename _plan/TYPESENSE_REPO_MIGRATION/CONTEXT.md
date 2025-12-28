# Contexto para Retomada (Amnésia LLM)

> Use este documento para recuperar contexto ao iniciar nova sessão.

## O Que Está Acontecendo

Estamos migrando o repositório `typesense` para dentro do repositório `data-platform`. O objetivo é consolidar toda a lógica de dados em um único repositório.

## Repositórios Envolvidos

```
destaquesgovbr/
├── typesense/           # ORIGEM - será descontinuado
├── data-platform/       # DESTINO - receberá o código
└── infra/               # Terraform - já tem Workload Identity configurado
```

## Arquivos Importantes para Leitura

1. **Este plano**: `_plan/TYPESENSE_REPO_MIGRATION/PLAN.md`
2. **Checklist de execução**: `_plan/TYPESENSE_REPO_MIGRATION/CHECKLIST.md`
3. **Decisões tomadas**: `_plan/TYPESENSE_REPO_MIGRATION/DECISIONS.md`
4. **Código fonte original**: `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/typesense/src/typesense_dgb/`

## Estado Atual

Verifique o CHECKLIST.md para saber qual fase está em andamento.

## Decisões Críticas Já Tomadas

1. **NÃO copiar dataset.py** - Leitura apenas do PostgreSQL
2. **Usar docker-compose** - Descartar run-typesense-server.sh
3. **Descartar typesense_sync.py existente** - Reusar código do typesense
4. **Adicionar content_embedding** - Campo de 768 dimensões no schema
5. **Renomear docker-build.yaml** - Para postgres-docker-build.yaml
6. **Mover Dockerfile** - Para docker/postgres/Dockerfile
7. **CLAUDE.md único** - Apenas na raiz, consolidado

## Estrutura de Diretórios (Meta Final)

```
data-platform/
├── src/data_platform/
│   ├── typesense/           # Módulo de conexão e schema
│   └── jobs/typesense/      # Jobs de sincronização
├── scripts/typesense/       # CLIs
├── docs/typesense/          # Documentação
├── docker/
│   ├── postgres/            # Dockerfile existente (movido)
│   └── typesense/           # Novo Dockerfile
└── .github/workflows/
    ├── postgres-docker-build.yaml    # Renomeado
    ├── typesense-docker-build.yaml   # Novo
    ├── typesense-daily-load.yaml     # Novo
    └── typesense-full-reload.yaml    # Novo
```

## Fluxo de Dados

```
PostgreSQL (news + themes + embeddings)
    ↓
get_news_for_typesense() [PostgresManager]
    ↓
sync_to_typesense() [sync_job.py]
    ↓
index_documents() [indexer.py]
    ↓
Typesense (collection "news")
```

## Comandos CLI (Após Migração)

```bash
# Sincronizar período específico
data-platform sync-typesense --start-date 2025-12-26 --end-date 2025-12-27

# Sincronização completa
data-platform sync-typesense --full-sync

# Listar coleções
data-platform typesense-list

# Deletar coleção
data-platform typesense-delete --confirm
```

## Variáveis de Ambiente Necessárias

```bash
# PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Typesense
TYPESENSE_HOST=34.39.186.38  # IP estático GCP
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=xxx
```

## Produção vs Local

- **Produção**: Typesense roda como systemd na VM GCP (não Docker)
- **Local**: Typesense via docker-compose

## Próximos Passos (Se Iniciando Nova Sessão)

1. Leia CHECKLIST.md para ver o progresso
2. Identifique qual fase está em andamento
3. Continue a partir do último item não marcado
4. Atualize CHECKLIST.md conforme concluir itens

## Comandos Úteis para Verificação

```bash
# Testar importação do módulo
python -c "from data_platform.typesense import get_client"

# Testar CLI
data-platform sync-typesense --help

# Build Docker
docker build -f docker/typesense/Dockerfile .

# Verificar workflows
gh workflow list
```
