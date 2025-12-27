# Database Migrations - Phase 4.7

Migrations para adicionar suporte a embeddings semânticos usando pgvector.

## Ordem de Execução

Execute as migrations nesta ordem:

```bash
# 1. Habilitar pgvector extension
psql $DATABASE_URL -f 001_add_pgvector_extension.sql

# 2. Adicionar colunas de embedding
psql $DATABASE_URL -f 002_add_embedding_column.sql

# 3. Criar índices HNSW
psql $DATABASE_URL -f 003_create_embedding_index.sql
```

## Validação

Após executar as migrations, valide:

```sql
-- Verificar pgvector habilitado
SELECT * FROM pg_extension WHERE extname = 'vector';

-- Verificar colunas criadas
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'news'
  AND column_name LIKE '%embedding%';

-- Verificar índices criados
SELECT indexname
FROM pg_indexes
WHERE tablename = 'news'
  AND indexname LIKE '%embedding%';
```

## Rollback

Para reverter as migrations (em ordem inversa):

```sql
-- 3. Remover índices
DROP INDEX IF EXISTS idx_news_content_embedding_hnsw;
DROP INDEX IF EXISTS idx_news_embedding_status;
DROP INDEX IF EXISTS idx_news_embedding_updated;
DROP INDEX IF EXISTS idx_news_published_at_2025;

-- 2. Remover colunas
ALTER TABLE news DROP COLUMN IF EXISTS content_embedding;
ALTER TABLE news DROP COLUMN IF EXISTS embedding_generated_at;

-- 1. Desabilitar pgvector (CUIDADO: pode afetar outras funcionalidades)
-- DROP EXTENSION IF EXISTS vector CASCADE;
```

## Estimativa de Storage

- **Embeddings** (~30k records de 2025): ~90 MB
- **HNSW index**: ~200 MB
- **Total adicional**: ~300 MB
