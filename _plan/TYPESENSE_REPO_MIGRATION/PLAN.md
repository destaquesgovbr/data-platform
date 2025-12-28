# Plano de Migração: typesense → data-platform

## Estrutura Final

```
data-platform/
├── .github/workflows/
│   ├── main-workflow.yaml                # Pipeline news (existente)
│   ├── postgres-docker-build.yaml        # Docker PostgreSQL (RENOMEAR)
│   ├── typesense-docker-build.yaml       # Docker Typesense ← NOVO
│   ├── typesense-daily-load.yaml         # Carga diária ← NOVO
│   └── typesense-full-reload.yaml        # Recarga completa ← NOVO
├── src/data_platform/
│   ├── typesense/                        # ← NOVO módulo
│   │   ├── __init__.py
│   │   ├── client.py                     # Conexão Typesense
│   │   ├── collection.py                 # Schema (COM content_embedding)
│   │   ├── indexer.py                    # Indexação (COM embeddings)
│   │   └── utils.py                      # Helpers
│   ├── jobs/
│   │   ├── typesense/                    # ← NOVO
│   │   │   ├── __init__.py
│   │   │   ├── sync_job.py               # Job principal: PG → Typesense
│   │   │   └── collection_ops.py         # Operações de coleção
│   │   └── embeddings/
│   │       └── embedding_generator.py    # Mantido
│   │       # typesense_sync.py DELETADO
│   └── ...
├── scripts/typesense/                    # ← NOVO
│   ├── __init__.py
│   ├── sync_to_typesense.py
│   ├── delete_collection.py
│   └── create_search_key.py
├── docs/typesense/                       # ← NOVO
│   ├── README.md
│   ├── setup.md
│   ├── development.md
│   └── data-management.md
├── docker/
│   ├── postgres/                         # ← MOVER Dockerfile atual
│   │   └── Dockerfile
│   └── typesense/                        # ← NOVO
│       ├── Dockerfile
│       └── entrypoint.sh
├── CLAUDE.md                             # Único, consolidado
└── pyproject.toml
```

---

# FASES DE EXECUÇÃO

## Fase 1: Preparação e Estrutura

**Objetivo**: Criar estrutura de diretórios e reorganizar arquivos existentes

### Passos:

1.1. Criar diretórios:
```bash
mkdir -p src/data_platform/typesense
mkdir -p src/data_platform/jobs/typesense
mkdir -p scripts/typesense
mkdir -p docs/typesense
mkdir -p docker/typesense
mkdir -p docker/postgres
```

1.2. Mover Dockerfile existente:
```bash
mv Dockerfile docker/postgres/Dockerfile
```

1.3. Renomear workflow:
```bash
mv .github/workflows/docker-build.yaml .github/workflows/postgres-docker-build.yaml
```

1.4. Atualizar postgres-docker-build.yaml:
- Corrigir path do Dockerfile: `docker/postgres/Dockerfile`

### Verificação:
- [ ] Diretórios criados
- [ ] Dockerfile movido para docker/postgres/
- [ ] Workflow renomeado
- [ ] Build do Docker ainda funciona

---

## Fase 2: Migração do Módulo Core (typesense/)

**Objetivo**: Copiar e adaptar código Python principal

### Arquivos a copiar:
| Origem (typesense) | Destino (data-platform) | Ação |
|---|---|---|
| `src/typesense_dgb/client.py` | `src/data_platform/typesense/client.py` | Copiar |
| `src/typesense_dgb/collection.py` | `src/data_platform/typesense/collection.py` | Copiar + modificar |
| `src/typesense_dgb/indexer.py` | `src/data_platform/typesense/indexer.py` | Copiar + modificar |
| `src/typesense_dgb/utils.py` | `src/data_platform/typesense/utils.py` | Copiar |
| `src/typesense_dgb/dataset.py` | ❌ NÃO COPIAR | Descartado |

### Modificações em collection.py:
```python
# Adicionar ao COLLECTION_SCHEMA["fields"]
{
    "name": "content_embedding",
    "type": "float[]",
    "num_dim": 768,
    "optional": True,
    "index": True,
}
```

### Modificações em indexer.py:
- Adicionar processamento de embeddings do PostgreSQL (pgvector → float[])
- Usar PostgresManager existente para leitura de dados
- Remover referências ao HuggingFace

### Criar __init__.py:
```python
from data_platform.typesense.client import get_client, wait_for_typesense
from data_platform.typesense.collection import (
    COLLECTION_NAME, COLLECTION_SCHEMA,
    create_collection, delete_collection, list_collections,
)
from data_platform.typesense.indexer import index_documents, prepare_document
from data_platform.typesense.utils import calculate_published_week

__all__ = [...]
```

### Verificação:
- [ ] Arquivos copiados
- [ ] Imports atualizados para `data_platform.typesense`
- [ ] Schema tem content_embedding
- [ ] Sem referências a HuggingFace
- [ ] `python -c "from data_platform.typesense import get_client"` funciona

---

## Fase 3: Jobs de Sincronização

**Objetivo**: Criar jobs que leem do PostgreSQL e indexam no Typesense

### Criar src/data_platform/jobs/typesense/sync_job.py:
```python
"""
Job de sincronização PostgreSQL → Typesense.
Substitui dataset.py + typesense_sync.py
"""

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.typesense import get_client, create_collection, index_documents

def sync_to_typesense(
    start_date: str,
    end_date: str = None,
    full_sync: bool = False,
    batch_size: int = 1000,
) -> dict:
    """
    Sincroniza notícias do PostgreSQL para Typesense.

    Args:
        start_date: Data inicial (YYYY-MM-DD)
        end_date: Data final (opcional)
        full_sync: Se True, recarrega tudo
        batch_size: Tamanho do lote

    Returns:
        Estatísticas de execução
    """
    pg_manager = PostgresManager()
    news_df = pg_manager.get_news_for_typesense(
        start_date=start_date,
        end_date=end_date,
    )
    client = get_client()
    create_collection(client)
    stats = index_documents(client, news_df, mode="upsert")
    return stats
```

### Adicionar método em PostgresManager:
```python
def get_news_for_typesense(self, start_date: str, end_date: str = None) -> pd.DataFrame:
    """Retorna news com JOINs de temas e embeddings para indexação no Typesense."""
    pass
```

### Criar src/data_platform/jobs/typesense/collection_ops.py:
- Funções para delete_collection, list_collections, create_search_key

### Verificação:
- [ ] sync_job.py criado
- [ ] PostgresManager.get_news_for_typesense() funciona
- [ ] Teste local: `sync_to_typesense("2025-12-26", "2025-12-26")` indexa dados
- [ ] Dados aparecem no Typesense com embeddings

---

## Fase 4: Scripts CLI

**Objetivo**: Criar comandos CLI para operações Typesense

### Atualizar cli.py:
```python
@app.command()
def sync_typesense(
    start_date: str = typer.Option(...),
    end_date: str = typer.Option(None),
    full_sync: bool = typer.Option(False),
):
    """Sincroniza PostgreSQL → Typesense."""
    from data_platform.jobs.typesense.sync_job import sync_to_typesense
    stats = sync_to_typesense(start_date, end_date, full_sync)
    typer.echo(f"Indexados: {stats['indexed']}")

@app.command()
def typesense_delete(confirm: bool = typer.Option(False)):
    """Deleta coleção Typesense."""
    pass

@app.command()
def typesense_list():
    """Lista coleções Typesense."""
    pass
```

### Verificação:
- [ ] `data-platform sync-typesense --start-date 2025-12-26` funciona
- [ ] `data-platform typesense-delete --confirm` funciona
- [ ] `data-platform typesense-list` funciona

---

## Fase 5: Docker

**Objetivo**: Migrar Dockerfile do Typesense indexer

### Copiar arquivos:
- `typesense/Dockerfile` → `docker/typesense/Dockerfile`
- `typesense/entrypoint.sh` → `docker/typesense/entrypoint.sh`

### Modificar Dockerfile:
```dockerfile
COPY src/data_platform/ /app/src/data_platform/
COPY scripts/typesense/ /app/scripts/typesense/
CMD ["data-platform", "sync-typesense", "--full-sync"]
```

### Verificação:
- [ ] `docker build -f docker/typesense/Dockerfile .` funciona
- [ ] Container executa sync corretamente

---

## Fase 6: Workflows GitHub Actions

**Objetivo**: Migrar e adaptar workflows

### Copiar e renomear:
| Origem | Destino |
|---|---|
| `docker-build-push.yml` | `typesense-docker-build.yaml` |
| `typesense-daily-load.yml` | `typesense-daily-load.yaml` |
| `typesense-full-reload.yml` | `typesense-full-reload.yaml` |

### Modificações em typesense-docker-build.yaml:
```yaml
paths:
  - 'src/data_platform/typesense/**'
  - 'docker/typesense/**'
  - 'scripts/typesense/**'

# Build:
docker build -f docker/typesense/Dockerfile ...
```

### Modificações em typesense-daily-load.yaml:
```yaml
data-platform sync-typesense --start-date "$START_DATE" --end-date "$END_DATE"
```

### Verificação:
- [ ] Workflows com syntax válida
- [ ] Paths atualizados
- [ ] Secrets/vars configurados

---

## Fase 7: Documentação

**Objetivo**: Migrar documentação e consolidar CLAUDE.md

### Copiar docs:
- `typesense/docs/setup.md` → `docs/typesense/setup.md`
- `typesense/docs/development.md` → `docs/typesense/development.md`
- `typesense/docs/data-management.md` → `docs/typesense/data-management.md`
- `typesense/README.md` (partes relevantes) → `docs/typesense/README.md`

### Atualizar CLAUDE.md raiz:
- Adicionar seção sobre Typesense
- Incluir estrutura do módulo typesense/
- Documentar comandos CLI
- NÃO copiar typesense/CLAUDE.md

### Verificação:
- [ ] Docs copiados
- [ ] Paths atualizados nos docs
- [ ] CLAUDE.md consolidado

---

## Fase 8: Limpeza

**Objetivo**: Remover arquivos obsoletos

### Deletar:
- `src/data_platform/jobs/embeddings/typesense_sync.py`

### NÃO migrar (descartar):
- `typesense/web-ui/`
- `typesense/run-typesense-server.sh`
- `typesense/MCP-ANALYSIS.md`
- `typesense/MCP-SERVER-STATUS.md`
- `typesense/init-typesense.py`
- `typesense/test_init_typesense.py`
- `typesense/DEBUG_PLAN.md`
- `typesense/WEEKLY_INDEX_OPTIMIZATION.md`
- `typesense/src/typesense_dgb/dataset.py`
- `typesense/CLAUDE.md`

### Verificação:
- [ ] typesense_sync.py deletado
- [ ] Nenhum arquivo desnecessário copiado
- [ ] Imports não quebrados

---

## Fase 9: Teste End-to-End

**Objetivo**: Validar toda a migração

### Testes locais:
```bash
# 1. Importação
python -c "from data_platform.typesense import get_client, index_documents"

# 2. CLI
data-platform sync-typesense --start-date 2025-12-26 --end-date 2025-12-26

# 3. Verificar no Typesense
curl "http://localhost:8108/collections/news" -H "X-TYPESENSE-API-KEY: ..."

# 4. Docker builds
docker build -f docker/postgres/Dockerfile .
docker build -f docker/typesense/Dockerfile .
```

### Teste em produção:
```bash
gh workflow run typesense-daily-load.yaml -f start_date=2025-12-26
```

### Verificação:
- [ ] Todos os imports funcionam
- [ ] CLI indexa dados corretamente
- [ ] Embeddings aparecem no Typesense
- [ ] Docker builds funcionam
- [ ] Workflow executa com sucesso

---

## Fase 10: Commit e Push

**Objetivo**: Finalizar migração

### Passos:
1. `git add .`
2. `git commit -m "feat: migrate typesense repo to data-platform"`
3. `git push`

### Verificação:
- [ ] CI passa
- [ ] Workflows executam
- [ ] Typesense recebe dados

---

## Arquivos Críticos

### A Modificar:
- `src/data_platform/typesense/collection.py` - adicionar content_embedding
- `src/data_platform/typesense/indexer.py` - processar embeddings
- `src/data_platform/managers/postgres_manager.py` - método get_news_for_typesense
- `src/data_platform/cli.py` - novos comandos
- `pyproject.toml` - entry points
- `CLAUDE.md` - consolidar contexto
- `.github/workflows/postgres-docker-build.yaml` - corrigir path Dockerfile

### A Criar:
- `src/data_platform/typesense/__init__.py`
- `src/data_platform/typesense/client.py`
- `src/data_platform/typesense/collection.py`
- `src/data_platform/typesense/indexer.py`
- `src/data_platform/typesense/utils.py`
- `src/data_platform/jobs/typesense/__init__.py`
- `src/data_platform/jobs/typesense/sync_job.py`
- `src/data_platform/jobs/typesense/collection_ops.py`
- `scripts/typesense/__init__.py`
- `docker/typesense/Dockerfile`
- `docker/typesense/entrypoint.sh`
- Workflows: `typesense-*.yaml`

### A Deletar:
- `src/data_platform/jobs/embeddings/typesense_sync.py`

### A Mover:
- `Dockerfile` → `docker/postgres/Dockerfile`

### A Renomear:
- `docker-build.yaml` → `postgres-docker-build.yaml`
