# 🚀 Quickstart: Teste Local Completo

Guia rápido para testar a migração completa localmente.

---

## Pré-requisitos

```bash
# 1. PostgreSQL rodando
sudo systemctl start postgresql  # ou pg_ctl start

# 2. Dependências Python
pip install -r requirements.txt

# 3. Dump disponível
ls -lh ../data_dump/Cloud_SQL_Export_*.sql
```

---

## Opção 1: Script Automático (RECOMENDADO) ⭐

```bash
./setup_local_test.sh
```

Este script faz TUDO:
- ✅ Cria banco `govbrnews_test`
- ✅ Ativa extensão `pgvector`
- ✅ Restaura dump completo (~10-15 min)
- ✅ Aplica migration 004 (dual embeddings)
- ✅ Mostra estatísticas

**Depois do script:**
```bash
# Exportar artigos
psql govbrnews_test < dump_articles_for_migration.sql

# Converter para Parquet
python csv_to_parquet.py /tmp/artigos_para_migrar.csv --sample 1000

# Testar migração
python migrate_to_bge_m3.py generate \
    --input artigos_para_migrar.parquet \
    --output embeddings_test.parquet \
    --batch-size 128

# Upload de volta
export DATABASE_URL='postgresql:///govbrnews_test'
python migrate_to_bge_m3.py upload \
    --input embeddings_test.parquet \
    --database-url $DATABASE_URL
```

---

## Opção 2: Passo a Passo Manual

### 1. Criar banco de testes
```bash
createdb govbrnews_test
psql govbrnews_test -c "CREATE EXTENSION vector;"
```

### 2. Restaurar dump
```bash
# Com progress bar (requer pv)
pv ../data_dump/Cloud_SQL_Export_*.sql | psql govbrnews_test

# Ou sem progress bar
psql govbrnews_test < ../data_dump/Cloud_SQL_Export_*.sql
```

**Aguarde:** ~10-15 minutos para 4.7 GB

### 3. Verificar dados
```bash
psql govbrnews_test -c "SELECT COUNT(*) FROM news;"
```

### 4. Aplicar migration 004
```bash
psql govbrnews_test < ../migrations/004_add_bge_m3_columns.sql
```

**Verifica:**
- ✅ Coluna `content_embedding_legacy` criada (768d)
- ✅ Coluna `content_embedding` criada (1024d)
- ✅ Coluna `embedding_model_version` criada
- ✅ Índice HNSW criado

### 5. Exportar artigos para migração
```bash
psql govbrnews_test < dump_articles_for_migration.sql
```

**Gera:** `/tmp/artigos_para_migrar.csv`

### 6. Converter para Parquet
```bash
# Sample de 1k para teste rápido
python csv_to_parquet.py /tmp/artigos_para_migrar.csv --sample 1000

# Ou todos (~300k)
python csv_to_parquet.py /tmp/artigos_para_migrar.csv
```

### 7. Gerar embeddings
```bash
python migrate_to_bge_m3.py generate \
    --input artigos_para_migrar.parquet \
    --output embeddings_test.parquet \
    --batch-size 128 \
    --device cuda  # ou cpu se não tiver GPU
```

**Tempo:**
- Com GPU L4: ~1 min para 1k, ~7 min para 10k
- Com CPU: ~30 min para 1k, ~5h para 10k

### 8. Upload para PostgreSQL
```bash
export DATABASE_URL='postgresql:///govbrnews_test'

python migrate_to_bge_m3.py upload \
    --input embeddings_test.parquet \
    --database-url $DATABASE_URL
```

### 9. Validar migração
```bash
psql govbrnews_test << 'EOF'
-- Verificar embeddings migrados
SELECT
    embedding_model_version,
    COUNT(*) as count,
    COUNT(*) FILTER (WHERE content_embedding IS NOT NULL) as with_bge_embedding,
    COUNT(*) FILTER (WHERE content_embedding_legacy IS NOT NULL) as with_legacy_embedding
FROM news
GROUP BY embedding_model_version;

-- Verificar dimensão
SELECT
    id,
    unique_id,
    embedding_model_version,
    array_length(content_embedding, 1) as bge_dim,
    array_length(content_embedding_legacy, 1) as legacy_dim
FROM news
WHERE embedding_model_version = 'bge-m3'
LIMIT 5;
EOF
```

**Esperado:**
- `embedding_model_version = 'bge-m3'`
- `bge_dim = 1024`
- `legacy_dim = 768` (se havia embedding anterior)

---

## Teste Completo End-to-End

```bash
#!/bin/bash
# Teste completo com sample de 100 artigos

set -e

echo "🧪 Teste End-to-End"
echo "=================="

# 1. Setup banco
./setup_local_test.sh

# 2. Export sample
psql govbrnews_test -c "
COPY (
    SELECT id, unique_id, title, summary, content
    FROM news
    WHERE content_embedding_legacy IS NOT NULL
    ORDER BY published_at DESC
    LIMIT 100
) TO '/tmp/sample_100.csv' WITH CSV HEADER;
"

# 3. Convert
python csv_to_parquet.py /tmp/sample_100.csv

# 4. Generate embeddings
python migrate_to_bge_m3.py generate \
    --input /tmp/sample_100.parquet \
    --output /tmp/sample_100_embeddings.parquet \
    --batch-size 32

# 5. Upload
export DATABASE_URL='postgresql:///govbrnews_test'
python migrate_to_bge_m3.py upload \
    --input /tmp/sample_100_embeddings.parquet \
    --database-url $DATABASE_URL

# 6. Validate
psql govbrnews_test -c "
SELECT
    COUNT(*) FILTER (WHERE embedding_model_version = 'bge-m3') as migrated,
    COUNT(*) as total
FROM news
WHERE id IN (
    SELECT id FROM news
    ORDER BY published_at DESC
    LIMIT 100
);
"

echo "✅ Teste completo!"
```

---

## Troubleshooting

### PostgreSQL não conecta
```bash
# Verificar se está rodando
pg_isready

# Iniciar
sudo systemctl start postgresql
# ou
pg_ctl -D /path/to/data start
```

### pgvector não encontrado
```bash
# Ubuntu/Debian
sudo apt install postgresql-16-pgvector

# macOS
brew install pgvector

# Ou compilar do source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

### GPU não disponível
```bash
# Verificar CUDA
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"

# Se False, usar CPU
python migrate_to_bge_m3.py generate --device cpu ...
```

---

## Limpeza

```bash
# Dropar banco de testes
dropdb govbrnews_test

# Remover arquivos temporários
rm -f /tmp/artigos_para_migrar.*
rm -f /tmp/sample_*
rm -f embeddings_*.parquet
rm -f migration.log
```

---

## Próximos Passos

Após validar localmente:

1. **Rodar na EC2 L4** com dados completos (~300k artigos)
2. **Aplicar migration 004** em produção
3. **Upload embeddings** para produção
4. **Re-indexar Typesense**
5. **Cleanup** (remover colunas legacy)

---

**Dúvidas?** Veja README.md completo ou abra issue.
