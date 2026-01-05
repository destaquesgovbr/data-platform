# Tracking: Integração Typesense Sync no Main Workflow

**Data Início**: 2025-12-30
**Status**: 🟡 Em Planejamento
**Executor**: Claude Sonnet 4.5

---

## 📋 Objetivos

- [ ] **OBJ-1**: Integrar sync do Typesense no main-workflow como último job
- [ ] **OBJ-2**: Remover workflow typesense-daily-load.yaml (substituído pelo main-workflow)
- [ ] **OBJ-3**: Refatorar typesense-full-reload.yaml → typesense-maintenance-sync.yaml
- [ ] **OBJ-4**: Remover parâmetro include_embeddings de todo código Python

---

## 🚀 Fase 1: Refatoração de Código Python

**Objetivo**: Remover parâmetro `include_embeddings` (sempre incluir embeddings)
**Impacto**: Baixo - Não afeta workflows existentes
**Arquivos**: 3 arquivos Python

### Tarefa 1.1: PostgreSQL Manager

- [ ] Abrir `src/data_platform/managers/postgres_manager.py`
- [ ] Modificar `_build_typesense_query()` (linha ~499)
  - [ ] Remover parâmetro `include_embeddings: bool = True`
  - [ ] Atualizar docstring
  - [ ] Linha ~537-538: Remover `if include_embeddings:` (sempre adicionar embedding)
- [ ] Modificar `iter_news_for_typesense()` (linha ~587)
  - [ ] Remover parâmetro `include_embeddings: bool = True`
  - [ ] Atualizar docstring (linha ~599)
  - [ ] Linha ~620: Remover argumento `include_embeddings` da chamada
- [ ] Modificar `get_news_for_typesense()` (linha ~657)
  - [ ] Remover parâmetro `include_embeddings: bool = True`
  - [ ] Atualizar docstring (linha ~669)
  - [ ] Linha ~683: Remover argumento `include_embeddings` da chamada
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado
**Commit**: `refactor(postgres): remove include_embeddings parameter from typesense queries`

### Tarefa 1.2: Typesense Sync Job

- [ ] Abrir `src/data_platform/jobs/typesense/sync_job.py`
- [ ] Modificar `sync_to_typesense()` (linha ~37)
  - [ ] Remover parâmetro `include_embeddings: bool = True`
  - [ ] Atualizar docstring (linha ~51)
  - [ ] Linha ~108: Remover argumento na chamada a `_sync_small_dataset()`
  - [ ] Linha ~121: Remover argumento na chamada a `iter_news_for_typesense()`
- [ ] Modificar `_sync_small_dataset()` (linha ~177)
  - [ ] Remover parâmetro `include_embeddings: bool`
  - [ ] Linha ~188: Remover argumento na chamada a `get_news_for_typesense()`
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado
**Commit**: `refactor(typesense): remove include_embeddings parameter from sync job`

### Tarefa 1.3: CLI

- [ ] Abrir `src/data_platform/cli.py`
- [ ] Modificar comando `sync-typesense` (linha ~189)
  - [ ] Linha ~195: Remover `include_embeddings: bool = typer.Option(True, ...)`
  - [ ] Linha ~201: Atualizar docstring ("Note: Always includes content embeddings")
  - [ ] Linha ~207: Remover referência a `include_embeddings` no logging
  - [ ] Linha ~214: Remover argumento `include_embeddings=include_embeddings`
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado
**Commit**: `refactor(cli): remove include_embeddings option from sync-typesense command`

### Tarefa 1.4: Testar Refatoração

- [ ] Executar: `poetry run data-platform sync-typesense --help`
- [ ] Verificar que `--include-embeddings` não aparece mais na help
- [ ] (Opcional) Testar sync local com parâmetros válidos

**Status**: ⬜ Não iniciado

### Tarefa 1.5: Commit da Fase 1

- [ ] Review das mudanças: `git diff`
- [ ] Stage: `git add src/data_platform/`
- [ ] Commit: `git commit -m "refactor: remove include_embeddings parameter (always include)"`
- [ ] Registrar hash do commit no EXECUTION_LOG.md

**Status**: ⬜ Não iniciado
**Commit Hash**: _pending_

---

## 🔧 Fase 2: Refatorar Workflow de Manutenção

**Objetivo**: Renomear e melhorar typesense-full-reload.yaml
**Impacto**: Baixo - Workflow manual
**Arquivos**: 1 workflow

### Tarefa 2.1: Renomear Arquivo

- [ ] Git: `git mv .github/workflows/typesense-full-reload.yaml .github/workflows/typesense-maintenance-sync.yaml`

**Status**: ⬜ Não iniciado

### Tarefa 2.2: Atualizar Metadata e Inputs

- [ ] Abrir `.github/workflows/typesense-maintenance-sync.yaml`
- [ ] Linha 1: Mudar name para `Typesense Maintenance Sync`
- [ ] Linhas 3-20: Substituir inputs:
  - [ ] Adicionar `operation_type` (choice: full-reload, incremental-sync)
  - [ ] Manter `confirm_deletion` (mas apenas para full-reload)
  - [ ] Manter `start_date` (required: true, default: '2024-01-01')
  - [ ] Adicionar `end_date` (optional, default vazio = today)
  - [ ] Adicionar `batch_size` (default: 1000)
  - [ ] Adicionar `max_records` (default: 0 = unlimited)
  - [ ] Manter `skip_portal_refresh`
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado

### Tarefa 2.3: Atualizar Steps do Workflow

- [ ] Step "Validate confirmation input" (linha ~36)
  - [ ] Adicionar: `if: github.event.inputs.operation_type == 'full-reload'`
- [ ] Step "Delete existing collection" (linha ~91)
  - [ ] Adicionar: `if: github.event.inputs.operation_type == 'full-reload'`
- [ ] Step "Calculate date range" (linha ~111)
  - [ ] Usar `github.event.inputs.start_date` e `github.event.inputs.end_date`
  - [ ] Se `end_date` vazio, usar `$(date +%Y-%m-%d)`
- [ ] Step "Run data sync" (linha ~120)
  - [ ] Adicionar lógica condicional para `--full-sync` flag
  - [ ] Adicionar `--batch-size ${{ github.event.inputs.batch_size }}`
  - [ ] Adicionar `--max-records` (se != 0)
- [ ] Step "Report final status" (linha ~158)
  - [ ] Incluir tipo de operação no summary
  - [ ] Mostrar batch_size e max_records
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado

### Tarefa 2.4: Commit da Fase 2

- [ ] Review: `git diff .github/workflows/typesense-maintenance-sync.yaml`
- [ ] Stage: `git add .github/workflows/typesense-maintenance-sync.yaml`
- [ ] Commit: `git commit -m "feat: enhance typesense maintenance workflow with flexible options"`
- [ ] Registrar hash do commit no EXECUTION_LOG.md

**Status**: ⬜ Não iniciado
**Commit Hash**: _pending_

---

## 🔗 Fase 3: Integrar no Main Workflow

**Objetivo**: Adicionar typesense-sync ao pipeline principal
**Impacto**: Alto - Muda pipeline de produção
**Arquivos**: 2 workflows (1 novo job, 1 deleção)

### Tarefa 3.1: Deletar typesense-daily-load.yaml

- [ ] Git: `git rm .github/workflows/typesense-daily-load.yaml`
- [ ] Confirmar remoção: `git status`

**Status**: ⬜ Não iniciado

### Tarefa 3.2: Adicionar Job typesense-sync ao main-workflow

- [ ] Abrir `.github/workflows/main-workflow.yaml`
- [ ] Localizar final do job `generate-embeddings` (linha ~287)
- [ ] Inserir novo job `typesense-sync` após linha 287:
  - [ ] `name: Sync to Typesense`
  - [ ] `needs: [setup-dates, generate-embeddings]`
  - [ ] `permissions: contents: read, id-token: write`
  - [ ] Steps:
    - [ ] Checkout code
    - [ ] Authenticate to Google Cloud
    - [ ] Fetch Typesense Config
    - [ ] Fetch Database URL
    - [ ] Set up Python 3.12
    - [ ] Install Poetry
    - [ ] Cache Poetry dependencies
    - [ ] Install dependencies
    - [ ] Sync data to Typesense (comando CLI)
    - [ ] Trigger portal cache refresh
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado

### Tarefa 3.3: Atualizar pipeline-summary

- [ ] Localizar job `pipeline-summary` (linha ~289)
- [ ] Linha ~292: Adicionar `typesense-sync` ao array `needs`
  - De: `needs: [setup-dates, scraper, ebc-scraper, upload-to-cogfy, enrich-themes, generate-embeddings]`
  - Para: `needs: [..., generate-embeddings, typesense-sync]`
- [ ] Linha ~303: Adicionar status do Typesense após "Embedding generation status"
  - `echo "Typesense sync status: ${{ needs.typesense-sync.result }}"`
- [ ] Linha ~306: Adicionar validação do typesense-sync no `if`
  - Adicionar: `&& [ "${{ needs.typesense-sync.result }}" = "success" ]`
- [ ] Salvar arquivo

**Status**: ⬜ Não iniciado

### Tarefa 3.4: Commit da Fase 3

- [ ] Review: `git diff .github/workflows/main-workflow.yaml`
- [ ] Review: `git status` (confirmar que daily-load foi removido)
- [ ] Stage: `git add .github/workflows/`
- [ ] Commit: `git commit -m "feat: integrate typesense sync into main workflow

- Add typesense-sync job as final step of daily pipeline
- Remove typesense-daily-load.yaml (replaced by main-workflow integration)
- Update pipeline-summary to include typesense-sync status

BREAKING: Typesense sync now runs at 4h UTC (within main-workflow)
instead of independent 10h UTC schedule."`
- [ ] Registrar hash do commit no EXECUTION_LOG.md

**Status**: ⬜ Não iniciado
**Commit Hash**: _pending_

---

## ✅ Testes de Validação

### Teste 1: Verificar CLI (Após Fase 1)

- [ ] Executar: `poetry run data-platform sync-typesense --help`
- [ ] Verificar ausência de `--include-embeddings`
- [ ] Verificar help text atualizado
- [ ] (Opcional) Testar sync com `--max-records 10`

**Status**: ⬜ Não iniciado
**Resultado**: _pending_

### Teste 2: Validar Workflow de Manutenção (Após Fase 2)

- [ ] GitHub UI: Acessar Actions → Typesense Maintenance Sync
- [ ] Verificar inputs disponíveis:
  - [ ] operation_type (dropdown com 2 opções)
  - [ ] confirm_deletion
  - [ ] start_date, end_date
  - [ ] batch_size, max_records
  - [ ] skip_portal_refresh
- [ ] (Opcional) Disparar workflow em modo incremental-sync

**Status**: ⬜ Não iniciado
**Resultado**: _pending_

### Teste 3: Validar Main Workflow (Após Fase 3)

- [ ] GitHub UI: Acessar Actions → Main News Processing Pipeline
- [ ] Verificar que typesense-daily-load.yaml não aparece mais
- [ ] Disparar main-workflow manualmente (date range curto: 2025-12-29 a 2025-12-30)
- [ ] Acompanhar execução:
  - [ ] Jobs anteriores executam normalmente
  - [ ] Job `typesense-sync` aguarda `generate-embeddings`
  - [ ] Job `typesense-sync` executa com sucesso
  - [ ] Job `pipeline-summary` inclui status do typesense-sync
- [ ] Verificar logs do typesense-sync

**Status**: ⬜ Não iniciado
**Resultado**: _pending_

---

## 📊 Status Geral

| Fase | Status | Commits | Testes |
|------|--------|---------|--------|
| **Fase 1**: Refatoração Python | ⬜ Não iniciado | 0/3 | 0/1 |
| **Fase 2**: Workflow Manutenção | ⬜ Não iniciado | 0/1 | 0/1 |
| **Fase 3**: Integração Main | ⬜ Não iniciado | 0/1 | 0/1 |
| **Total** | **0%** | **0/5** | **0/3** |

---

## 🔄 Progresso por Arquivo

### Código Python (3 arquivos)

- [ ] `src/data_platform/managers/postgres_manager.py` - 3 funções modificadas
- [ ] `src/data_platform/jobs/typesense/sync_job.py` - 2 funções modificadas
- [ ] `src/data_platform/cli.py` - 1 comando modificado

### Workflows (3 arquivos)

- [ ] `.github/workflows/typesense-full-reload.yaml` → `typesense-maintenance-sync.yaml` - Renomeado e expandido
- [ ] `.github/workflows/typesense-daily-load.yaml` - **DELETADO**
- [ ] `.github/workflows/main-workflow.yaml` - 1 job adicionado, 1 job atualizado

---

## ⚠️ Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação | Status |
|-------|---------------|---------|-----------|--------|
| Quebrar workflows ao remover include_embeddings | Baixa | Alto | Executar Fase 1 primeiro, testar antes de mudar workflows | ⬜ |
| Sync do Typesense não rodar mais às 10h UTC | Certa | Médio | Comunicar mudança (agora roda às 4h UTC no main-workflow) | ⬜ |
| Pipeline-summary falhar se typesense-sync falhar | Baixa | Médio | Summary tem `if: always()`, apenas reporta status | ⬜ |
| Parâmetros do maintenance-sync confusos | Baixa | Baixo | Documentação clara nos inputs e values default | ⬜ |

---

## 📝 Notas de Execução

### Decisões Tomadas

1. **Remover completamente typesense-daily-load.yaml**: Ao invés de apenas remover o schedule, deletar o arquivo inteiro. O sync agora roda exclusivamente no main-workflow.

2. **Manter typesense-maintenance-sync.yaml flexível**: Suporta tanto full-reload quanto incremental-sync, permitindo operações manuais quando necessário.

3. **Sempre incluir embeddings**: Decisão de simplificação - não faz sentido sincronizar sem embeddings.

### Próximos Passos Após Conclusão

1. Atualizar documentação do projeto mencionando nova localização do sync
2. Comunicar ao time a mudança de horário (10h UTC → 4h UTC)
3. Monitorar primeira execução automática do main-workflow com typesense-sync

---

## 🎯 Resultado Final Esperado

### Pipeline Completo (4h UTC diariamente)

```
Main Workflow:
  setup-dates
    ↓
  scraper
    ↓
  ebc-scraper
    ↓
  upload-to-cogfy
    ↓
  enrich-themes
    ↓
  generate-embeddings
    ↓
  typesense-sync ← NOVO
    ↓
  pipeline-summary (atualizado)
```

### Workflows Disponíveis

1. **main-workflow.yaml**: Pipeline completo diário (automático 4h UTC)
2. **typesense-maintenance-sync.yaml**: Sync manual com todas as opções
3. ~~**typesense-daily-load.yaml**~~: **REMOVIDO**

### Código Simplificado

- ✅ Parâmetro `include_embeddings` removido de 3 arquivos Python
- ✅ 6 funções simplificadas (sempre incluem embeddings)
- ✅ CLI mais limpo (um parâmetro a menos)

---

**Última Atualização**: 2025-12-30
**Próxima Revisão**: Após cada fase concluída
