# Plano: Fix Parquet Schema Mismatch

**Data:** 2026-01-13
**Issue:** https://github.com/destaquesgovbr/data-platform/actions/runs/20944951239

---

## Problema Identificado

O Main Workflow falha ao carregar o dataset porque os shards novos criados pela DAG `sync_postgres_to_huggingface` tem schema **incompativel** com os arquivos base.

### Schema dos arquivos BASE (originais):
```
published_at:       timestamp[us, tz=-03:00]  <- timestamp com timezone
updated_datetime:   timestamp[us, tz=-03:00]  <- timestamp com timezone
extracted_at:       timestamp[ns]             <- timestamp naive (sem tz)
```

### Schema dos SHARDS novos (criados pela DAG):
```
published_at:       string   <- "2026-01-07T22:42:16+00:00"
updated_datetime:   string   <- ISO string
extracted_at:       string   <- ISO string com +00:00
```

### Causa Raiz

O codigo atual em `sync_postgres_to_huggingface.py` (linhas 157-161) converte timestamps para **strings ISO**:

```python
if hasattr(value, 'isoformat'):
    if hasattr(value, 'tzinfo') and value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    value = value.isoformat()  # <- Converte para STRING
```

Isso cria parquets com colunas `string` ao inves de `timestamp`.

---

## Arquivos Afetados no HuggingFace

| Arquivo | Status | Problema |
|---------|--------|----------|
| `train-00000-of-00003.parquet` | OK | Base, schema correto |
| `train-00001-of-00003.parquet` | OK | Base, schema correto |
| `train-00002-of-00003.parquet` | OK | Base, schema correto |
| `train-2026-01-07-090031.parquet` | **DELETAR** | Schema string, dados duplicados |
| `train-2026-01-07-131930.parquet` | **DELETAR** | Schema string |
| `train-2026-01-08-090032.parquet` | **DELETAR** | Schema string |
| `train-2026-01-09-090030.parquet` | **DELETAR** | Schema string |
| `train-2026-01-10-090030.parquet` | **DELETAR** | Schema string |
| `train-2026-01-11-090030.parquet` | **DELETAR** | Schema string |
| `train-2026-01-12-090032.parquet` | **DELETAR** | Schema string |

**Total:** 7 shards a deletar

---

## Solucao Proposta

### Fase 1: Corrigir o Codigo da DAG

Alterar `sync_postgres_to_huggingface.py` para:

1. **NAO converter timestamps para strings** - manter como objetos datetime
2. **Usar PyArrow schema explicito** que corresponda ao schema base:
   - `published_at`: `pa.timestamp('us', tz='-03:00')`
   - `updated_datetime`: `pa.timestamp('us', tz='-03:00')`
   - `extracted_at`: `pa.timestamp('ns')` (naive)

```python
import pyarrow as pa

PARQUET_SCHEMA = pa.schema([
    ('unique_id', pa.string()),
    ('agency', pa.string()),
    ('published_at', pa.timestamp('us', tz='-03:00')),
    ('updated_datetime', pa.timestamp('us', tz='-03:00')),
    ('extracted_at', pa.timestamp('ns')),
    ('title', pa.string()),
    ('subtitle', pa.string()),
    ('editorial_lead', pa.string()),
    ('url', pa.string()),
    ('content', pa.string()),
    ('image', pa.string()),
    ('video_url', pa.string()),
    ('category', pa.string()),
    ('tags', pa.list_(pa.string())),
    # ... campos de theme/AI
])
```

### Fase 2: Deletar Shards Inconsistentes

Deletar todos os shards com schema errado do HuggingFace:

```bash
# Via huggingface_hub
from huggingface_hub import HfApi
api = HfApi()

files_to_delete = [
    "data/train-2026-01-07-090031.parquet",
    "data/train-2026-01-07-131930.parquet",
    "data/train-2026-01-08-090032.parquet",
    "data/train-2026-01-09-090030.parquet",
    "data/train-2026-01-10-090030.parquet",
    "data/train-2026-01-11-090030.parquet",
    "data/train-2026-01-12-090032.parquet",
]

for f in files_to_delete:
    api.delete_file(path_in_repo=f, repo_id="nitaibezerra/govbrnews", repo_type="dataset")
```

### Fase 3: Re-sincronizar Dados

Apos corrigir a DAG e deletar shards:

1. Disparar a DAG manualmente para cada dia faltante (07-12 janeiro)
2. Ou aguardar execucoes automaticas recriarem os dados

### Fase 4: Validar

1. Re-executar Main Workflow
2. Verificar que dataset carrega sem erros

---

## Alternativa: Migrar para Schema String

Se quisermos manter timestamps como strings (mais simples):

1. Converter arquivos BASE para usar strings tambem
2. Recriar dataset inteiro com schema consistente

**Desvantagem:** Perda de tipagem forte, queries menos eficientes

**Recomendacao:** Manter timestamps nativos (Fase 1-4)

---

## Ordem de Execucao

1. [ ] Corrigir `sync_postgres_to_huggingface.py` com schema explicito
2. [ ] Commit e deploy da correcao
3. [ ] Deletar shards inconsistentes do HuggingFace
4. [ ] Disparar DAG para re-sincronizar dados de 07-12 janeiro
5. [ ] Re-executar Main Workflow para validar

---

## Risco

- **Dados de 07-12 janeiro ficarao indisponiveis** ate re-sincronizar
- **Volume:** ~7 dias x ~80 registros/dia = ~560 registros temporariamente ausentes
- **Mitigacao:** Processo pode ser feito em ~30 minutos

---

## Referencias

- DAG: `src/data_platform/dags/sync_postgres_to_huggingface.py`
- Dataset: https://huggingface.co/datasets/nitaibezerra/govbrnews
- Workflow: `.github/workflows/main-workflow.yaml`
