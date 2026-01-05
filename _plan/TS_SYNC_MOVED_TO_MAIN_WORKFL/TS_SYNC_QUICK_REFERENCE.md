# Quick Reference: Typesense Sync Integration

**Resumo executivo das mudanças para consulta rápida**

---

## 🎯 O Que Mudou

### 1. Código Python (3 arquivos)

**Parâmetro `include_embeddings` REMOVIDO** - Embeddings sempre incluídos agora.

```python
# ❌ ANTES
sync_to_typesense(..., include_embeddings=True)

# ✅ DEPOIS
sync_to_typesense(...)  # Sempre inclui embeddings
```

**Arquivos afetados**:
- `src/data_platform/managers/postgres_manager.py` (3 funções)
- `src/data_platform/jobs/typesense/sync_job.py` (2 funções)
- `src/data_platform/cli.py` (1 comando)

### 2. Workflows (3 arquivos)

| Antes | Depois | Mudança |
|-------|--------|---------|
| `typesense-daily-load.yaml` | **DELETADO** | Sync movido para main-workflow |
| `typesense-full-reload.yaml` | `typesense-maintenance-sync.yaml` | Renomeado + novos parâmetros |
| `main-workflow.yaml` | `main-workflow.yaml` | +1 job (`typesense-sync`) |

### 3. Horário do Sync Automático

- **Antes**: 10h UTC (workflow independente)
- **Depois**: 4h UTC (integrado ao main-workflow)

---

## 📋 Comandos CLI

### Antes da Mudança

```bash
poetry run data-platform sync-typesense \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --include-embeddings \  # ← Removido
  --batch-size 1000
```

### Depois da Mudança

```bash
poetry run data-platform sync-typesense \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --batch-size 1000
  # Embeddings sempre incluídos automaticamente
```

### Novos Parâmetros (mantidos)

- `--start-date` (required)
- `--end-date` (optional, default: start_date)
- `--full-sync` (flag, default: false)
- `--batch-size` (default: 1000)
- `--max-records` (optional, para testes)

---

## 🔄 Workflows GitHub Actions

### Main Workflow (Diário - 4h UTC)

**Jobs atualizados**:
```yaml
setup-dates → scraper → ebc-scraper → upload-to-cogfy →
enrich-themes → generate-embeddings → typesense-sync → pipeline-summary
                                        ↑ NOVO JOB
```

**Trigger**:
- Schedule: `0 4 * * *` (4h UTC = 1h Brasília)
- workflow_dispatch (manual)

### Typesense Maintenance Sync (Manual)

**Novo nome**: `typesense-maintenance-sync.yaml`

**Inputs**:
- `operation_type`: `full-reload` ou `incremental-sync`
- `confirm_deletion`: Confirmação para full-reload (tipo "DELETE")
- `start_date`: Data inicial (required, default: 2024-01-01)
- `end_date`: Data final (optional, default: hoje)
- `batch_size`: Tamanho do batch (default: 1000)
- `max_records`: Limite para testes (default: 0 = ilimitado)
- `skip_portal_refresh`: Pular refresh do portal (default: false)

**Uso típico**:
- **Full reload**: operation_type=full-reload + confirm_deletion=DELETE
- **Sync incremental**: operation_type=incremental-sync + date range

---

## 📁 Estrutura de Arquivos

### Código Python

```
src/data_platform/
├── cli.py                           # ✏️ Modificado
├── managers/
│   └── postgres_manager.py          # ✏️ Modificado
└── jobs/typesense/
    └── sync_job.py                  # ✏️ Modificado
```

### Workflows

```
.github/workflows/
├── main-workflow.yaml               # ✏️ Modificado (+1 job)
├── typesense-daily-load.yaml        # ❌ DELETADO
├── typesense-full-reload.yaml       # 🔄 RENOMEADO ↓
└── typesense-maintenance-sync.yaml  # ✅ NOVO (renomeado)
```

---

## 🔍 Diferenças Principais

### Pipeline Principal

| Aspecto | Antes | Depois |
|---------|-------|--------|
| Jobs | 6 jobs | 7 jobs (+typesense-sync) |
| Duração estimada | ~45 min | ~50 min |
| Sync automático | Não | Sim (às 4h UTC) |
| Summary | 6 jobs | 7 jobs |

### Workflow de Manutenção

| Aspecto | Antes (full-reload) | Depois (maintenance-sync) |
|---------|---------------------|---------------------------|
| Nome | Typesense Full Data Reload | Typesense Maintenance Sync |
| Modos | Apenas full reload | Full reload + Incremental |
| Parâmetros | 3 inputs | 7 inputs |
| Flexibilidade | Baixa | Alta |

### Código Python

| Aspecto | Antes | Depois |
|---------|-------|--------|
| Parâmetros sync | 6 parâmetros | 5 parâmetros (-include_embeddings) |
| Embeddings | Opcional (default: true) | Sempre incluídos |
| Complexidade | Lógica condicional | Simplificado |

---

## ⚡ Cheat Sheet

### Como fazer sync incremental manual agora?

**Antes** (typesense-daily-load.yaml):
```
GitHub Actions → Typesense Daily Incremental Load → Run workflow
Inputs: days=7
```

**Depois** (typesense-maintenance-sync.yaml):
```
GitHub Actions → Typesense Maintenance Sync → Run workflow
Inputs:
  operation_type: incremental-sync
  start_date: 2025-12-24
  end_date: 2025-12-30
```

### Como fazer full reload agora?

**Antes** (typesense-full-reload.yaml):
```
GitHub Actions → Typesense Full Data Reload → Run workflow
Inputs:
  confirm_deletion: DELETE
  start_date: 2024-01-01
```

**Depois** (typesense-maintenance-sync.yaml):
```
GitHub Actions → Typesense Maintenance Sync → Run workflow
Inputs:
  operation_type: full-reload
  confirm_deletion: DELETE
  start_date: 2024-01-01
  end_date: (deixar vazio para hoje)
```

### Como testar sync localmente?

```bash
# Setup
export TYPESENSE_HOST="localhost"
export TYPESENSE_PORT="8108"
export TYPESENSE_API_KEY="local_dev_key_12345"
export DATABASE_URL="postgresql://user:pass@localhost:5432/db"

# Sync pequeno para teste
poetry run data-platform sync-typesense \
  --start-date 2025-12-30 \
  --end-date 2025-12-30 \
  --batch-size 100 \
  --max-records 50
```

---

## 📊 Impacto por Stakeholder

### Desenvolvedores

- ✅ Código mais simples (sem `include_embeddings`)
- ✅ CLI mais limpo
- ⚠️ Precisa lembrar que embeddings sempre incluídos agora

### DevOps

- ✅ Um workflow a menos para manter (daily-load deletado)
- ✅ Workflow de manutenção mais flexível
- ⚠️ Sync agora parte do pipeline principal (falha = pipeline falha)

### Usuários Finais

- ✅ Dados sincronizados mais cedo (4h UTC vs 10h UTC)
- ✅ Sync integrado ao pipeline (menos chances de inconsistência)
- ⬜ Sem impacto visível (mudança interna)

---

## 🚨 Breaking Changes

### Para Código Python

```python
# ❌ Isso vai quebrar
from data_platform.jobs.typesense import sync_to_typesense
sync_to_typesense(..., include_embeddings=False)
# TypeError: sync_to_typesense() got an unexpected keyword argument 'include_embeddings'

# ✅ Fazer isso
sync_to_typesense(...)  # Embeddings sempre incluídos
```

### Para CI/CD

- **Antes**: Daily sync às 10h UTC (typesense-daily-load.yaml)
- **Depois**: Daily sync às 4h UTC (dentro do main-workflow)

**Ação necessária**: Nenhuma - mudança automática após merge

### Para Scripts Externos

Se algum script externo invocava o workflow `typesense-daily-load.yaml`:

```bash
# ❌ Isso vai quebrar (workflow não existe mais)
gh workflow run typesense-daily-load.yaml -f days=7

# ✅ Fazer isso
gh workflow run typesense-maintenance-sync.yaml \
  -f operation_type=incremental-sync \
  -f start_date=2025-12-24 \
  -f end_date=2025-12-30
```

---

## 📞 FAQ

### P: E se eu precisar rodar sync fora do pipeline?

**R**: Use `typesense-maintenance-sync.yaml` com `operation_type=incremental-sync`

### P: O sync diário ainda roda?

**R**: Sim, mas agora às 4h UTC (dentro do main-workflow) ao invés de 10h UTC

### P: Posso desabilitar embeddings?

**R**: Não. Decisão de design: embeddings sempre incluídos (simplifica código)

### P: Como sei se o sync rodou com sucesso?

**R**: Veja o status do job `typesense-sync` no pipeline-summary do main-workflow

### P: Onde estão os logs do sync?

**R**: GitHub Actions → Main News Processing Pipeline → Job "Sync to Typesense"

### P: O que acontece se typesense-sync falhar?

**R**: Pipeline-summary reporta falha, mas ainda executa (tem `if: always()`)

---

**Última Atualização**: 2025-12-30
**Versão**: 1.0
