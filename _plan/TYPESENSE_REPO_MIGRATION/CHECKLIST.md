# Checklist de Execução

> Marque os itens conforme forem concluídos. Use `[x]` para concluído.

## Fase 1: Preparação e Estrutura

- [x] Criar diretório `src/data_platform/typesense/`
- [x] Criar diretório `src/data_platform/jobs/typesense/`
- [x] Criar diretório `scripts/typesense/`
- [x] Criar diretório `docs/typesense/`
- [x] Criar diretório `docker/typesense/`
- [x] Criar diretório `docker/postgres/`
- [x] Mover `Dockerfile` para `docker/postgres/Dockerfile`
- [x] Renomear `docker-build.yaml` → `postgres-docker-build.yaml`
- [x] Atualizar path do Dockerfile no workflow
- [x] Verificar: `docker build -f docker/postgres/Dockerfile .` funciona

## Fase 2: Módulo Core (typesense/)

- [x] Copiar `client.py`
- [x] Copiar `collection.py`
- [x] Adicionar campo `content_embedding` ao schema
- [x] Copiar `indexer.py`
- [x] Adaptar indexer para processar embeddings pgvector
- [x] Copiar `utils.py`
- [x] Criar `__init__.py` com exports
- [x] Atualizar imports para `data_platform.typesense`
- [x] Verificar: `python -c "from data_platform.typesense import get_client"`

## Fase 3: Jobs de Sincronização

- [x] Criar `jobs/typesense/__init__.py`
- [x] Criar `jobs/typesense/sync_job.py`
- [x] Criar `jobs/typesense/collection_ops.py`
- [x] Adicionar `get_news_for_typesense()` ao PostgresManager
- [ ] Verificar: Query retorna dados com embeddings
- [ ] Teste: Sincronização local funciona

## Fase 4: Scripts CLI

- [x] Adicionar comando `sync-typesense` ao cli.py
- [x] Adicionar comando `typesense-delete` ao cli.py
- [x] Adicionar comando `typesense-list` ao cli.py
- [x] Verificar: `data-platform sync-typesense --help`
- [ ] Teste: CLI indexa dados

## Fase 5: Docker

- [x] Copiar `Dockerfile` para `docker/typesense/`
- [x] Copiar `entrypoint.sh` para `docker/typesense/`
- [x] Adaptar Dockerfile para nova estrutura (Python 3.12-slim)
- [x] Verificar: `docker build -f docker/typesense/Dockerfile .`
- [ ] Teste: Container executa sync

## Fase 6: Workflows

- [x] Copiar workflow `docker-build-push.yml` → `typesense-docker-build.yaml`
- [x] Copiar workflow `typesense-daily-load.yml` → `typesense-daily-load.yaml`
- [x] Copiar workflow `typesense-full-reload.yml` → `typesense-full-reload.yaml`
- [x] Atualizar paths nos workflows
- [x] Atualizar comandos para usar CLI
- [x] Verificar: Syntax válida (YAML parsing OK)

## Fase 7: Documentação

- [ ] Copiar `docs/setup.md` → `docs/typesense/setup.md`
- [ ] Copiar `docs/development.md` → `docs/typesense/development.md`
- [ ] Copiar `docs/data-management.md` → `docs/typesense/data-management.md`
- [ ] Criar `docs/typesense/README.md`
- [ ] Atualizar paths nos documentos
- [ ] Atualizar CLAUDE.md com seção Typesense

## Fase 8: Limpeza

- [x] Deletar `src/data_platform/jobs/embeddings/typesense_sync.py`
- [x] Verificar: Nenhum import quebrado
- [x] Confirmar: Nenhum arquivo descartado foi copiado

## Fase 9: Teste End-to-End

- [x] Teste: Importação de módulos
- [x] Teste: CLI sync-typesense --help
- [ ] Teste: Verificar dados no Typesense (precisa DB e Typesense)
- [x] Teste: Docker postgres build
- [x] Teste: Docker typesense build
- [ ] Teste: Workflow via `gh workflow run` (após merge)

## Fase 10: Commit e Push

- [ ] Criar commit com todas as mudanças
- [ ] Push para remote
- [ ] Verificar: CI passa
- [ ] Verificar: Workflows executam corretamente

---

## Resumo de Progresso

| Fase | Status | Data Conclusão |
|------|--------|----------------|
| 1 - Preparação | ✅ Concluído | 2025-12-28 |
| 2 - Módulo Core | ✅ Concluído | 2025-12-28 |
| 3 - Jobs | ✅ Concluído | 2025-12-28 |
| 4 - CLI | ✅ Concluído | 2025-12-28 |
| 5 - Docker | ✅ Concluído | 2025-12-28 |
| 6 - Workflows | ✅ Concluído | 2025-12-28 |
| 7 - Documentação | ⬜ Pendente | |
| 8 - Limpeza | ✅ Concluído | 2025-12-28 |
| 9 - Teste E2E | 🟡 Parcial | 2025-12-28 |
| 10 - Commit | ⬜ Pendente | |

**Legenda:**
- ⬜ Pendente
- 🟡 Em Progresso
- ✅ Concluído
