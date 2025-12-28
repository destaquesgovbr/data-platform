# Checklist de Execução

> Marque os itens conforme forem concluídos. Use `[x]` para concluído.

## Fase 1: Preparação e Estrutura

- [ ] Criar diretório `src/data_platform/typesense/`
- [ ] Criar diretório `src/data_platform/jobs/typesense/`
- [ ] Criar diretório `scripts/typesense/`
- [ ] Criar diretório `docs/typesense/`
- [ ] Criar diretório `docker/typesense/`
- [ ] Criar diretório `docker/postgres/`
- [ ] Mover `Dockerfile` para `docker/postgres/Dockerfile`
- [ ] Renomear `docker-build.yaml` → `postgres-docker-build.yaml`
- [ ] Atualizar path do Dockerfile no workflow
- [ ] Verificar: `docker build -f docker/postgres/Dockerfile .` funciona

## Fase 2: Módulo Core (typesense/)

- [ ] Copiar `client.py`
- [ ] Copiar `collection.py`
- [ ] Adicionar campo `content_embedding` ao schema
- [ ] Copiar `indexer.py`
- [ ] Adaptar indexer para processar embeddings pgvector
- [ ] Copiar `utils.py`
- [ ] Criar `__init__.py` com exports
- [ ] Atualizar imports para `data_platform.typesense`
- [ ] Verificar: `python -c "from data_platform.typesense import get_client"`

## Fase 3: Jobs de Sincronização

- [ ] Criar `jobs/typesense/__init__.py`
- [ ] Criar `jobs/typesense/sync_job.py`
- [ ] Criar `jobs/typesense/collection_ops.py`
- [ ] Adicionar `get_news_for_typesense()` ao PostgresManager
- [ ] Verificar: Query retorna dados com embeddings
- [ ] Teste: Sincronização local funciona

## Fase 4: Scripts CLI

- [ ] Adicionar comando `sync-typesense` ao cli.py
- [ ] Adicionar comando `typesense-delete` ao cli.py
- [ ] Adicionar comando `typesense-list` ao cli.py
- [ ] Verificar: `data-platform sync-typesense --help`
- [ ] Teste: CLI indexa dados

## Fase 5: Docker

- [ ] Copiar `Dockerfile` para `docker/typesense/`
- [ ] Copiar `entrypoint.sh` para `docker/typesense/`
- [ ] Adaptar Dockerfile para nova estrutura
- [ ] Verificar: `docker build -f docker/typesense/Dockerfile .`
- [ ] Teste: Container executa sync

## Fase 6: Workflows

- [ ] Copiar workflow `docker-build-push.yml` → `typesense-docker-build.yaml`
- [ ] Copiar workflow `typesense-daily-load.yml` → `typesense-daily-load.yaml`
- [ ] Copiar workflow `typesense-full-reload.yml` → `typesense-full-reload.yaml`
- [ ] Atualizar paths nos workflows
- [ ] Atualizar comandos para usar CLI
- [ ] Verificar: Syntax válida com `gh workflow view`

## Fase 7: Documentação

- [ ] Copiar `docs/setup.md` → `docs/typesense/setup.md`
- [ ] Copiar `docs/development.md` → `docs/typesense/development.md`
- [ ] Copiar `docs/data-management.md` → `docs/typesense/data-management.md`
- [ ] Criar `docs/typesense/README.md`
- [ ] Atualizar paths nos documentos
- [ ] Atualizar CLAUDE.md com seção Typesense

## Fase 8: Limpeza

- [ ] Deletar `src/data_platform/jobs/embeddings/typesense_sync.py`
- [ ] Verificar: Nenhum import quebrado
- [ ] Confirmar: Nenhum arquivo descartado foi copiado

## Fase 9: Teste End-to-End

- [ ] Teste: Importação de módulos
- [ ] Teste: CLI sync-typesense
- [ ] Teste: Verificar dados no Typesense
- [ ] Teste: Docker postgres build
- [ ] Teste: Docker typesense build
- [ ] Teste: Workflow via `gh workflow run`

## Fase 10: Commit e Push

- [ ] Criar commit com todas as mudanças
- [ ] Push para remote
- [ ] Verificar: CI passa
- [ ] Verificar: Workflows executam corretamente

---

## Resumo de Progresso

| Fase | Status | Data Conclusão |
|------|--------|----------------|
| 1 - Preparação | ⬜ Pendente | |
| 2 - Módulo Core | ⬜ Pendente | |
| 3 - Jobs | ⬜ Pendente | |
| 4 - CLI | ⬜ Pendente | |
| 5 - Docker | ⬜ Pendente | |
| 6 - Workflows | ⬜ Pendente | |
| 7 - Documentação | ⬜ Pendente | |
| 8 - Limpeza | ⬜ Pendente | |
| 9 - Teste E2E | ⬜ Pendente | |
| 10 - Commit | ⬜ Pendente | |

**Legenda:**
- ⬜ Pendente
- 🟡 Em Progresso
- ✅ Concluído
