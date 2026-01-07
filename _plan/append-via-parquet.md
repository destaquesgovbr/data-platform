# Plano: Corrigir OOM na DAG sync_postgres_to_huggingface

## Problema Atual

A DAG `sync_postgres_to_huggingface` está falhando com OOM após ~7-8 minutos.
- Workers do Composer têm apenas **2GB RAM**
- Dataset HuggingFace tem ~310k registros
- Código atual carrega TODO o dataset + múltiplas cópias pandas

---

## Pesquisa: Capacidades da API HuggingFace

### 1. Dataset Viewer API - Consultar SEM baixar

O HuggingFace oferece o endpoint `/filter` que permite consultar dados via API:

```bash
# Consultar se unique_id existe (sem baixar dataset)
curl "https://datasets-server.huggingface.co/filter?\
dataset=nitaibezerra/govbrnews&\
config=default&\
split=train&\
where=\"unique_id\"='gov-br-123'&\
length=1"
```

**Limitações:**
- Máximo 100 rows por request
- Datasets >5GB: apenas primeiros 5GB indexados
- Requer dataset em formato Parquet (✅ já usamos)

### 2. Escrita Incremental - append=True

**NÃO existe `push_to_hub(..., append=True)`** - feature request ainda aberta ([Issue #6290](https://github.com/huggingface/datasets/issues/6290)).

**Workaround oficial:**
- Fazer upload de novo arquivo parquet diretamente
- Usar `CommitOperationAdd` do `huggingface_hub`
- Xet storage (default desde maio 2025) faz dedup automático de chunks

---

## Solução Recomendada: Append via Parquet Shards

**Ideia:** Não carregar dataset existente. Apenas:
1. Consultar unique_ids via API `/filter` (paginado)
2. Filtrar novos registros
3. Criar novo parquet shard
4. Upload direto via `huggingface_hub`

### Implementação

```python
from huggingface_hub import HfApi, CommitOperationAdd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from datetime import datetime

DATASET_PATH = "nitaibezerra/govbrnews"
API_BASE = "https://datasets-server.huggingface.co"

def get_existing_ids_for_date(target_date: str) -> set:
    """Consulta unique_ids do dia via API (sem baixar dataset)."""
    existing_ids = set()
    offset = 0

    while True:
        # Filtrar por published_at do dia específico
        url = f"{API_BASE}/filter"
        params = {
            "dataset": DATASET_PATH,
            "config": "default",
            "split": "train",
            "where": f"\"published_at\">'{target_date}' AND \"published_at\"<'{target_date}T23:59:59'",
            "offset": offset,
            "length": 100,
        }
        resp = requests.get(url, params=params)
        data = resp.json()

        rows = data.get("rows", [])
        if not rows:
            break

        for row in rows:
            existing_ids.add(row["row"]["unique_id"])

        offset += 100
        if len(rows) < 100:
            break

    return existing_ids

def sync_incremental(new_records: list, target_date: str):
    """Faz append incremental via parquet shard."""

    # 1. Consultar IDs existentes para o dia (via API, sem download)
    existing_ids = get_existing_ids_for_date(target_date)

    # 2. Filtrar apenas novos
    new_only = [r for r in new_records if r["unique_id"] not in existing_ids]

    if not new_only:
        return {"status": "skipped", "reason": "all records already exist"}

    # 3. Criar parquet shard
    table = pa.Table.from_pydict({
        col: [r[col] for r in new_only]
        for col in new_only[0].keys()
    })

    # Salvar em arquivo temporário
    shard_name = f"data/train-{target_date}-{datetime.now().strftime('%H%M%S')}.parquet"
    local_path = f"/tmp/{shard_name.replace('/', '_')}"
    pq.write_table(table, local_path)

    # 4. Upload direto (sem carregar dataset existente)
    api = HfApi()
    api.upload_file(
        path_or_fileobj=local_path,
        path_in_repo=shard_name,
        repo_id=DATASET_PATH,
        repo_type="dataset",
        commit_message=f"Add {len(new_only)} news from {target_date}",
    )

    return {"status": "success", "records_added": len(new_only)}
```

### Vantagens

| Aspecto | Antes (load_dataset) | Depois (API + Parquet) |
|---------|---------------------|------------------------|
| Memória | ~1-2GB (todo dataset) | ~10MB (só novos registros) |
| Tempo | 7-8 min (timeout) | ~30 seg |
| Deduplicação | ✅ | ✅ (via API filter) |
| Dependências | `datasets` (pesado) | `huggingface_hub`, `pyarrow` |

### Limitações a Considerar

1. **Fragmentação**: Cria muitos arquivos parquet pequenos ao longo do tempo
   - Mitigação: Rodar consolidação semanal/mensal

2. **API rate limits**: Não documentados, mas paginação de 100 rows
   - Mitigação: Filtrar por `published_at` do dia (poucos registros)

3. **Ordenação**: Não mantém ordem global do dataset
   - Mitigação: Ordenar na query do consumidor, ou consolidar periodicamente

---

## Arquivos a Modificar

- `src/data_platform/dags/sync_postgres_to_huggingface.py` - Reescrever com abordagem incremental

---

## Implementação Detalhada

### Fase 1: Reescrever a DAG

**Arquivo:** `src/data_platform/dags/sync_postgres_to_huggingface.py`

**Mudanças:**
1. Remover `load_dataset()` e lógica de merge
2. Adicionar função `get_existing_ids_for_date()` usando API `/filter`
3. Criar parquet shard com `pyarrow`
4. Upload via `HfApi.upload_file()`

**Dependências (requirements.txt):**
```
huggingface-hub==0.27.0
pyarrow>=14.0.0
requests
```
(Remover `datasets==3.2.0`)

### Fase 2: Consolidação Periódica (Opcional)

Criar DAG separada `consolidate_huggingface_dataset.py` que:
- Roda semanalmente
- Baixa todos os shards
- Consolida em arquivos maiores
- Reenvia para o Hub

---

## Próximos Passos

1. [ ] Testar endpoint `/filter` com nosso dataset (validar sintaxe)
2. [ ] Reescrever DAG com abordagem incremental
3. [ ] Atualizar requirements.txt (remover `datasets`)
4. [ ] Deploy e testar
5. [ ] Criar issue para job de consolidação periódica
