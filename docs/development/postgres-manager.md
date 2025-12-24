# PostgresManager

Gerenciador de armazenamento PostgreSQL para DestaquesGovBr.

---

## Visão Geral

O `PostgresManager` é a interface principal para interagir com o banco de dados PostgreSQL. Ele fornece:

- **Connection pooling** para melhor performance
- **Cache em memória** para agencies e themes
- **Operações em batch** para insert/update
- **Rastreamento de sincronização** com HuggingFace

---

## Uso Básico

### Inicialização

```python
from data_platform.managers import PostgresManager

# Auto-detecta connection string (Secret Manager ou localhost)
manager = PostgresManager()

# Ou especifica connection string manualmente
manager = PostgresManager(
    connection_string="postgresql://user:pass@host:5432/db",
    min_connections=2,
    max_connections=10
)
```

### Context Manager

```python
with PostgresManager() as manager:
    # Usar manager
    news = manager.get_by_unique_id("abc123")
# Conexões automaticamente fechadas
```

---

## Operações

### Carregar Cache

```python
# Carrega agencies e themes para cache em memória
manager.load_cache()

# Buscar agency por key (usa cache)
agency = manager.get_agency_by_key("mec")
# Agency(id=112, key='mec', name='Ministério da Educação')

# Buscar theme por code (usa cache)
theme = manager.get_theme_by_code("01")
# Theme(id=1, code='01', label='Economia e Finanças', level=1)
```

### Insert

```python
from data_platform.models import NewsInsert
from datetime import datetime, timezone

# Criar notícia
news = NewsInsert(
    unique_id="unique_abc123",
    agency_id=112,
    title="Nova notícia do MEC",
    url="https://www.gov.br/mec/...",
    content="Conteúdo da notícia...",
    published_at=datetime.now(timezone.utc),
    agency_key="mec",
    agency_name="Ministério da Educação"
)

# Inserir (batch)
inserted = manager.insert([news])  # Retorna quantidade inserida

# Inserir com allow_update (upsert)
inserted = manager.insert([news], allow_update=True)
```

### Update

```python
# Atualizar campos
updated = manager.update(
    "unique_abc123",
    {"summary": "Resumo gerado por IA", "tags": ["educação", "mec"]}
)
# True se atualizou, False se não encontrou
```

### Get

```python
# Buscar por unique_id
news = manager.get_by_unique_id("unique_abc123")

# Buscar com filtros
news_list = manager.get(
    filters={"agency_id": 112},
    limit=10,
    offset=0,
    order_by="published_at DESC"
)

# Contar
total = manager.count()
count_mec = manager.count({"agency_id": 112})
```

### Sincronização HuggingFace

```python
# Buscar registros que precisam ser sincronizados
to_sync = manager.get_records_for_hf_sync(limit=1000)

# Processar sincronização...

# Marcar como sincronizado
unique_ids = [n.unique_id for n in to_sync]
manager.mark_as_synced_to_hf(unique_ids)
```

---

## Modelos

### News

Modelo completo de notícia (inclui todos os campos, inclusive generated).

```python
from data_platform.models import News

news = News(
    id=1,
    unique_id="abc123",
    agency_id=112,
    title="Título",
    published_at=datetime.now(timezone.utc),
    # ... outros campos
)
```

### NewsInsert

Modelo para operações de insert (sem campos generated como `id`, `created_at`).

```python
from data_platform.models import NewsInsert

news = NewsInsert(
    unique_id="abc123",
    agency_id=112,
    title="Título",
    published_at=datetime.now(timezone.utc),
    # Não inclui id, created_at, updated_at
)
```

### Agency

```python
from data_platform.models import Agency

agency = Agency(
    id=1,
    key="mec",
    name="Ministério da Educação",
    type="Ministério"
)
```

### Theme

```python
from data_platform.models import Theme

theme = Theme(
    id=1,
    code="01",
    label="Economia e Finanças",
    level=1,
    parent_code=None
)
```

---

## Connection String

O PostgresManager auto-detecta a connection string:

1. **Cloud SQL Proxy detectado** (via `pgrep`):
   - Busca password do Secret Manager
   - Usa `localhost:5432` como host
   - Formato: `postgresql://govbrnews_app:{password}@127.0.0.1:5432/govbrnews`

2. **Sem Cloud SQL Proxy**:
   - Usa connection string direta do Secret Manager
   - Formato: `postgresql://govbrnews_app:{password}@10.5.0.3:5432/govbrnews`

### Secret Manager

A senha é armazenada em:
```
gcloud secrets versions access latest \
  --secret=govbrnews-postgres-connection-string
```

---

## Connection Pooling

O PostgresManager usa `psycopg2.pool.SimpleConnectionPool`:

- **Default**: 1-10 conexões
- **Configurável** via parâmetros `min_connections` e `max_connections`
- **Thread-safe**: Múltiplas threads podem usar o mesmo pool

```python
manager = PostgresManager(
    min_connections=5,   # Mínimo de conexões mantidas
    max_connections=20   # Máximo de conexões simultâneas
)
```

---

## Cache

### Comportamento

- Cache carregado sob demanda no primeiro uso de `get_agency_by_key()` ou `get_theme_by_code()`
- Ou explicitamente com `manager.load_cache()`
- Cache persiste durante toda a vida do objeto `PostgresManager`

### Conteúdo

- `_agencies_by_key`: Dict[str, Agency] (159 registros)
- `_agencies_by_id`: Dict[int, Agency] (159 registros)
- `_themes_by_code`: Dict[str, Theme] (588 registros)
- `_themes_by_id`: Dict[int, Theme] (588 registros)

### Atualização

Cache não é atualizado automaticamente. Para refresh:

```python
# Recarregar cache
manager._cache_loaded = False
manager.load_cache()
```

---

## Testes

### Unit Tests

```bash
PYTHONPATH=src pytest tests/unit/test_postgres_manager.py -v
```

**Cobre**:
- Inicialização e configuração
- Métodos de cache (get_agency_by_key, get_theme_by_code)
- Validação de entrada (listas/dicts vazios)
- Context manager
- Modelos Pydantic

### Integration Tests

```bash
PYTHONPATH=src pytest tests/integration/test_postgres_integration.py -v
```

**Requer**:
- PostgreSQL acessível (via Cloud SQL Proxy ou local)
- Tabelas `agencies` e `themes` populadas

**Cobre**:
- Conexão real com banco
- Insert, update, get operations
- Sincronização HF
- Batch operations
- Upsert (allow_update=True)

---

## Exemplo Completo

```python
from data_platform.managers import PostgresManager
from data_platform.models import NewsInsert
from datetime import datetime, timezone

with PostgresManager() as manager:
    # 1. Carregar cache
    manager.load_cache()

    # 2. Buscar agency
    agency = manager.get_agency_by_key("mec")
    print(f"Agency: {agency.name} (id={agency.id})")

    # 3. Criar e inserir notícia
    news = NewsInsert(
        unique_id=f"test_{datetime.now().timestamp()}",
        agency_id=agency.id,
        title="Teste de Notícia",
        url="https://example.com/test",
        published_at=datetime.now(timezone.utc),
        agency_key=agency.key,
        agency_name=agency.name
    )

    inserted = manager.insert([news])
    print(f"Inserted: {inserted}")

    # 4. Buscar notícia inserida
    retrieved = manager.get_by_unique_id(news.unique_id)
    print(f"Retrieved: {retrieved.title}")

    # 5. Atualizar
    manager.update(news.unique_id, {"summary": "Resumo teste"})

    # 6. Contar
    total = manager.count({"agency_id": agency.id})
    print(f"Total news for {agency.key}: {total}")
```

---

## Troubleshooting

### ModuleNotFoundError: No module named 'data_platform'

**Solução**:
```bash
# Usar PYTHONPATH
PYTHONPATH=src python seu_script.py

# Ou instalar em modo editable (requer resolver dependências)
pip install -e .
```

### Connection failed: password authentication failed

**Possíveis causas**:
1. Cloud SQL Proxy não está rodando
2. Password no Secret Manager está incorreto
3. User `govbrnews_app` não existe ou sem permissões

**Debug**:
```bash
# Verificar se proxy está rodando
ps aux | grep cloud-sql-proxy

# Verificar secret
gcloud secrets versions access latest \
  --secret=govbrnews-postgres-connection-string

# Testar conexão manual
psql postgresql://govbrnews_app:password@127.0.0.1:5432/govbrnews
```

### Pydantic warnings (deprecated Config)

**Causa**: Modelos usam `class Config` (Pydantic v1 style)

**Solução** (futuro): Migrar para `ConfigDict`:
```python
from pydantic import BaseModel, ConfigDict

class News(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    # ...
```

---

## Próximos Passos

- [ ] Implementar retry logic para operações de banco
- [ ] Adicionar métricas (latência, pool usage)
- [ ] Implementar read replicas para queries
- [ ] Migrar models para Pydantic v2 style
- [ ] Adicionar transaction support
- [ ] Implementar soft deletes

---

**Última atualização**: 2024-12-24
