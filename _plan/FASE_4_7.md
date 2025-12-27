# Fase 4.7: Embeddings Semanticos

> **Status**: Em desenvolvimento
> **Objetivo**: Adicionar geracao de embeddings semanticos para noticias de 2025 e sincronizacao com Typesense para busca semantica.
> **Ultima atualizacao**: 2025-12-27

---

## Visao Geral

Esta fase implementa embeddings semanticos para habilitar busca por similaridade no portal DestaquesGovBr.

**Pipeline atual + embeddings**:
```
Pipeline Diario:
  scraper -> PostgreSQL
      |
  upload-cogfy -> Cogfy API (gera summary)
      |
  [wait 20 min]
      |
  enrich-themes -> PostgreSQL (themes + summary)
      |
  [NOVO] generate-embeddings -> PostgreSQL (embeddings de title + summary)
      |
  [NOVO] sync-embeddings-to-typesense -> Typesense (campo content_embedding)
```

> **IMPORTANTE**: Esta fase processa **apenas noticias de 2025** pois somente elas possuem resumos AI-gerados pelo Cogfy. Noticias anteriores nao serao processadas nesta fase.

---

## Decisoes Tecnicas

| Decisao | Escolha | Justificativa |
|---------|---------|---------------|
| **Modelo** | paraphrase-multilingual-mpnet-base-v2 (768 dims) | Ja usado para temas, excelente portugues, local (gratis), consistente |
| **Input** | `title + " " + summary` | Summary e AI-generated (Cogfy), mais semantico que content bruto |
| **Escopo** | **Apenas 2025** | Somente 2025 tem summaries do Cogfy |
| **Timing** | Job separado APOS enrich-themes | Garante que summary esta disponivel |
| **Storage** | PostgreSQL (pgvector) + Typesense | PG para queries avancadas, Typesense para MCP Server |
| **Sync** | Job separado PG -> Typesense | Modular, permite re-sync sem re-gerar |

---

## Subfases de Teste e Validacao

Para garantir a qualidade da implementacao antes do deploy em producao, a Fase 4.7 e dividida em 4 subfases de teste e validacao:

### Subfase 4.7.1: Setup PostgreSQL + pgvector local

**Objetivo**: Configurar ambiente local completo para testar geracao de embeddings.

**Pre-requisitos**:
- Docker Desktop rodando
- Branch `feature/phase-4.7-embeddings` checked out
- Poetry instalado

**Acoes**:

1. **Atualizar docker-compose.yml para incluir pgvector**
   - Modificar `docker/postgres/init.sql`
   - Adicionar `CREATE EXTENSION IF NOT EXISTS vector;` no inicio

2. **Subir ambiente local**
   ```bash
   cd /Users/nitai/Dropbox/dev-mgi/destaquesgovbr/data-platform
   make docker-reset  # Limpar e recriar
   make docker-up
   ```

3. **Rodar migrations de embeddings**
   ```bash
   docker exec -i destaquesgovbr-postgres psql -U destaquesgovbr_dev -d destaquesgovbr_dev < scripts/migrations/001_add_pgvector_extension.sql
   docker exec -i destaquesgovbr-postgres psql -U destaquesgovbr_dev -d destaquesgovbr_dev < scripts/migrations/002_add_embedding_column.sql
   docker exec -i destaquesgovbr-postgres psql -U destaquesgovbr_dev -d destaquesgovbr_dev < scripts/migrations/003_create_embedding_index.sql
   ```

4. **Popular dados de dezembro 2025 (para teste)**
   ```bash
   export DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"
   poetry run data-platform migrate-from-hf --start-date 2025-12-01 --end-date 2025-12-27
   ```

5. **Gerar embeddings (teste com 100 registros)**
   ```bash
   poetry run data-platform generate-embeddings \
     --start-date 2025-12-01 \
     --end-date 2025-12-27 \
     --max-records 100
   ```

**Validacao**:
```sql
-- Verificar embeddings gerados
SELECT COUNT(*) FROM news WHERE content_embedding IS NOT NULL;
SELECT unique_id, title, embedding_generated_at,
       array_length(content_embedding::float[], 1) as dims
FROM news
WHERE content_embedding IS NOT NULL
LIMIT 5;
```

**Arquivos a criar/modificar**:
- [ ] `docker/postgres/init.sql` - Adicionar pgvector extension

---

### Subfase 4.7.2: Setup Typesense local + Sync

**Objetivo**: Configurar Typesense local e testar sincronizacao de embeddings.

**Acoes**:

1. **Adicionar Typesense ao docker-compose.yml**
   ```yaml
   typesense:
     image: typesense/typesense:0.25.2
     container_name: destaquesgovbr-typesense
     ports:
       - "8108:8108"
     volumes:
       - typesense_data:/data
     environment:
       TYPESENSE_DATA_DIR: /data
       TYPESENSE_API_KEY: local_dev_key_12345
     networks:
       - destaquesgovbr-network
     healthcheck:
       test: ["CMD", "curl", "-f", "http://localhost:8108/health"]
       interval: 10s
       timeout: 5s
       retries: 5
   ```

2. **Criar script para inicializar collection com schema de embeddings**
   ```bash
   # scripts/init_typesense_collection.sh
   curl -X POST "http://localhost:8108/collections" \
     -H "Content-Type: application/json" \
     -H "X-TYPESENSE-API-KEY: local_dev_key_12345" \
     -d '{
       "name": "news",
       "fields": [
         {"name": "id", "type": "string"},
         {"name": "unique_id", "type": "string"},
         {"name": "title", "type": "string"},
         {"name": "agency", "type": "string", "facet": true},
         {"name": "published_at", "type": "int64"},
         {"name": "content_embedding", "type": "float[]", "num_dim": 768}
       ]
     }'
   ```

3. **Sincronizar embeddings para Typesense**
   ```bash
   export TYPESENSE_HOST="localhost"
   export TYPESENSE_PORT="8108"
   export TYPESENSE_API_KEY="local_dev_key_12345"

   poetry run data-platform sync-embeddings-to-typesense \
     --start-date 2025-12-01 \
     --end-date 2025-12-27 \
     --max-records 100
   ```

**Validacao**:
```bash
# Verificar documentos no Typesense
curl "http://localhost:8108/collections/news" \
  -H "X-TYPESENSE-API-KEY: local_dev_key_12345"

# Verificar count
curl "http://localhost:8108/collections/news/documents/search?q=*&per_page=0" \
  -H "X-TYPESENSE-API-KEY: local_dev_key_12345"
```

**Arquivos a criar/modificar**:
- [ ] `docker-compose.yml` - Adicionar servico Typesense
- [ ] `scripts/init_typesense_collection.sh` - Script de inicializacao

---

### Subfase 4.7.3: Testar consultas semanticas

**Objetivo**: Validar que busca semantica funciona corretamente em PostgreSQL e Typesense.

**Acoes**:

1. **Criar script de teste de consultas**
   - Arquivo: `scripts/test_semantic_search.py`
   - Gerar embedding para query de teste
   - Buscar similares no PostgreSQL (usando `<=>` operador)
   - Buscar similares no Typesense (vector search)
   - Comparar resultados

2. **Testar busca semantica no PostgreSQL**
   ```sql
   -- Primeiro, obter embedding de uma noticia existente
   WITH query_embedding AS (
       SELECT content_embedding
       FROM news
       WHERE title LIKE '%educacao%'
       LIMIT 1
   )
   SELECT
       unique_id,
       title,
       1 - (content_embedding <=> (SELECT content_embedding FROM query_embedding)) as similarity
   FROM news
   WHERE content_embedding IS NOT NULL
   ORDER BY content_embedding <=> (SELECT content_embedding FROM query_embedding)
   LIMIT 10;
   ```

3. **Testar busca semantica no Typesense**
   ```bash
   # Busca por vetor similar
   curl -X POST "http://localhost:8108/multi_search" \
     -H "Content-Type: application/json" \
     -H "X-TYPESENSE-API-KEY: local_dev_key_12345" \
     -d '{
       "searches": [{
         "collection": "news",
         "q": "*",
         "vector_query": "content_embedding:([0.1, 0.2, ...], k:10)"
       }]
     }'
   ```

4. **Criar teste automatizado**
   - Arquivo: `tests/integration/test_semantic_search.py`
   - Gerar embedding para texto de teste
   - Buscar em ambas as fontes
   - Verificar que resultados sao consistentes
   - Verificar que similaridade e calculada corretamente

**Criterios de Validacao**:
- [ ] Top 10 resultados sao relevantes para a query
- [ ] Resultados PostgreSQL e Typesense sao consistentes
- [ ] Performance aceitavel (<500ms para 30k registros)

**Arquivos a criar**:
- [ ] `scripts/test_semantic_search.py` - Script de teste manual
- [ ] `tests/integration/test_semantic_search.py` - Teste automatizado

---

### Subfase 4.7.4: Backfill producao

**Objetivo**: Gerar embeddings para todos os dados de 2025 e sincronizar com Typesense de producao.

**Pre-requisitos**:
- [ ] Subfases 4.7.1-4.7.3 validadas localmente
- [ ] PR #11 aprovado e merged
- [ ] Migrations rodadas em producao
- [ ] GPU disponivel (local ou cloud)

**Acoes**:

#### Opcao A: Backfill Local com GPU (Recomendado)
```bash
# 1. Configurar conexao com Cloud SQL
export DATABASE_URL="postgresql://user:pass@<cloud-sql-ip>/govbrnews"

# 2. Instalar PyTorch com CUDA
pip install torch --index-url https://download.pytorch.org/whl/cu118

# 3. Rodar backfill (dados de 2025)
poetry run data-platform generate-embeddings \
  --start-date 2025-01-01 \
  --end-date 2025-12-27 \
  --batch-size 500  # Maior batch size com GPU

# Estimativa: ~30k registros, ~15-20 minutos com GPU
```

#### Opcao B: Backfill via GitHub Actions (Mais lento)
```yaml
# Criar workflow manual para backfill
# ~2-3 horas para 30k registros (CPU only)
```

#### Sincronizar com Typesense de Producao
```bash
export TYPESENSE_HOST="typesense.producao.exemplo"
export TYPESENSE_API_KEY="<prod-key>"

poetry run data-platform sync-embeddings-to-typesense \
  --start-date 2025-01-01 \
  --end-date 2025-12-27 \
  --full-sync
```

**Validacao Producao**:
```sql
-- Verificar cobertura
SELECT
  COUNT(*) FILTER (WHERE content_embedding IS NOT NULL) as with_embeddings,
  COUNT(*) as total,
  ROUND(100.0 * COUNT(*) FILTER (WHERE content_embedding IS NOT NULL) / COUNT(*), 2) as pct
FROM news
WHERE published_at >= '2025-01-01';

-- Esperado: ~100% para 2025
```

**Monitoramento**:
- [ ] Verificar logs de erro
- [ ] Monitorar uso de CPU/memoria
- [ ] Verificar latencia do Typesense

---

## Resumo de Arquivos a Criar/Modificar

| Arquivo | Acao | Subfase |
|---------|------|---------|
| `docker/postgres/init.sql` | Modificar | 4.7.1 |
| `docker-compose.yml` | Modificar | 4.7.2 |
| `scripts/init_typesense_collection.sh` | Criar | 4.7.2 |
| `scripts/test_semantic_search.py` | Criar | 4.7.3 |
| `tests/integration/test_semantic_search.py` | Criar | 4.7.3 |

---

## Ordem de Execucao

```
4.7.1 Setup PostgreSQL + pgvector (local)
  |
4.7.2 Setup Typesense + Sync (local)
  |
4.7.3 Testar Consultas Semanticas
  |
[Merge PR #11]
  |
4.7.4 Backfill Producao
```

---

## Estimativa de Tempo

| Subfase | Tempo Estimado |
|---------|----------------|
| 4.7.1 Setup PostgreSQL | ~30 min |
| 4.7.2 Setup Typesense | ~30 min |
| 4.7.3 Testar Consultas | ~1 hora |
| 4.7.4 Backfill Producao | ~30 min (GPU) / ~3h (CPU) |

**Total**: ~2-3 horas (com GPU local)

---

## Tarefas Principais da Fase 4.7

- [ ] 4.7.1 Habilitar pgvector extension no Cloud SQL
- [ ] 4.7.2 Adicionar colunas de embedding a tabela news
- [ ] 4.7.3 Criar indices HNSW para busca vetorial
- [ ] 4.7.4 Implementar EmbeddingGenerator
- [ ] 4.7.5 Implementar TypesenseSyncManager
- [ ] 4.7.6 Adicionar comandos CLI (generate-embeddings, sync-embeddings-to-typesense)
- [ ] 4.7.7 Escrever testes automatizados (unit + integration)
- [ ] 4.7.8 Atualizar workflow GitHub Actions
- [ ] 4.7.9 Atualizar schema do Typesense
- [ ] 4.7.10 Testar localmente com Docker (PostgreSQL + Typesense)
- [ ] 4.7.11 Backfill embeddings para 2025

---

## Criterios de Conclusao

- [ ] pgvector habilitado no Cloud SQL
- [ ] Embeddings gerados para todas noticias de 2025
- [ ] Cobertura de embeddings > 95% para 2025
- [ ] Typesense sincronizado com embeddings
- [ ] Pipeline diario funciona com 2 novos jobs
- [ ] Testes passam (unit + integration)
- [ ] Busca semantica funciona no Typesense MCP Server
- [ ] Documentacao atualizada

---

*Documento mantido em: `/destaquesgovbr/data-platform/_plan/FASE_4_7.md`*
