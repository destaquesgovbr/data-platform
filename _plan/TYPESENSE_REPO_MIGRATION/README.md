# Migração: typesense → data-platform

> **Status**: 🟡 Em Execução (Fases 1-8 concluídas)
> **Criado**: 2025-12-28
> **Última Atualização**: 2025-12-28
> **PR**: https://github.com/destaquesgovbr/data-platform/pull/16

## Objetivo

Consolidar o repositório `typesense` no repositório `data-platform`, unificando toda a lógica de dados.

## Documentos

| Documento | Descrição |
|-----------|-----------|
| [PLAN.md](./PLAN.md) | Plano detalhado com 10 fases |
| [CHECKLIST.md](./CHECKLIST.md) | Checklist de execução por fase |
| [CONTEXT.md](./CONTEXT.md) | Contexto para retomada (amnésia LLM) |
| [DECISIONS.md](./DECISIONS.md) | Decisões tomadas e justificativas |

## Decisões Confirmadas

- ✅ **docker-compose only**: Descartar `run-typesense-server.sh`
- ✅ **Descartar typesense_sync.py**: Reusar código do typesense repo
- ✅ **Dockerfiles organizados**: `docker/postgres/` e `docker/typesense/`
- ✅ **Descartada web-ui/**: Interface web não será migrada
- ✅ **Sem dataset.py**: Leitura apenas do PostgreSQL
- ✅ **Renomear docker-build.yaml**: Para `postgres-docker-build.yaml`
- ✅ **CLAUDE.md único**: Manter apenas um na raiz

## Progresso

| Fase | Status | Descrição |
|------|--------|-----------|
| 1 | ✅ Concluído | Preparação e Estrutura |
| 2 | ✅ Concluído | Migração do Módulo Core |
| 3 | ✅ Concluído | Jobs de Sincronização |
| 4 | ✅ Concluído | Scripts CLI |
| 5 | ✅ Concluído | Docker |
| 6 | ✅ Concluído | Workflows GitHub Actions |
| 7 | ✅ Concluído | Documentação |
| 8 | ✅ Concluído | Limpeza |
| 9 | 🟡 Parcial | Teste End-to-End |
| 10 | ⬜ Pendente | Commit e Push |

## Estrutura Final

```
data-platform/
├── .github/workflows/
│   ├── main-workflow.yaml                # Pipeline news (existente)
│   ├── postgres-docker-build.yaml        # Docker PostgreSQL (RENOMEADO)
│   ├── typesense-docker-build.yaml       # Docker Typesense (NOVO)
│   ├── typesense-daily-load.yaml         # Carga diária (NOVO)
│   └── typesense-full-reload.yaml        # Recarga completa (NOVO)
├── src/data_platform/
│   ├── typesense/                        # NOVO módulo
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── collection.py
│   │   ├── indexer.py
│   │   └── utils.py
│   ├── jobs/typesense/                   # NOVO
│   │   ├── __init__.py
│   │   ├── sync_job.py
│   │   └── collection_ops.py
│   └── ...
├── scripts/typesense/                    # NOVO
├── docs/typesense/                       # NOVO
├── docker/
│   ├── postgres/                         # Dockerfile atual MOVIDO
│   │   └── Dockerfile
│   └── typesense/                        # NOVO
│       ├── Dockerfile
│       └── entrypoint.sh
└── CLAUDE.md                             # Único, consolidado
```
