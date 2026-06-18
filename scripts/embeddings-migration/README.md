# Migração de Embeddings: mpnet-768d → BGE-M3-1024d

Scripts para migração offline de embeddings usando GPU (EC2 L4).

**Relacionado:**
- Issue: data-platform#175
- Model validation: data-science#1
- Plano completo: `PLANO_MIGRACAO_BGE_M3.md` (repo infra)

---

## 📋 Overview

Esta migração processa ~300k artigos offline (EC2 + GPU L4) sem impactar a API principal.

**Vantagens:**
- ✅ Zero impacto na produção
- ✅ ~50-100x mais rápido que CPU (GPU L4)
- ✅ 1-2 dias vs 30 dias
- ✅ Custo: $0 (EC2 já existe)

---

## 🚀 Quick Start

### Pré-requisitos

```bash
# Instalar dependências
pip install pandas pyarrow sentence-transformers torch psycopg2-binary tqdm

# Verificar GPU (EC2)
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### Pipeline Completo (3 passos)

```bash
# 1. Dump PostgreSQL → CSV
psql $DATABASE_URL < dump_articles_for_migration.sql

# 2. CSV → Parquet (mais eficiente)
python csv_to_parquet.py /tmp/artigos_para_migrar.csv

# 3. Gerar embeddings + Upload
python migrate_to_bge_m3.py full \
    --input artigos_para_migrar.parquet \
    --database-url $DATABASE_URL
```

---

## 📖 Guia Detalhado

### Passo 1: Dump do PostgreSQL

**Objetivo:** Exportar artigos que precisam migração.

```bash
# Conectar ao banco
psql $DATABASE_URL

# Executar script SQL
\i dump_articles_for_migration.sql

# Saída: /tmp/artigos_para_migrar.csv
```

**Critérios de seleção:**
- `embedding_model_version = 'mpnet'` (embeddings legados)
- OU `content_embedding IS NULL AND content_embedding_legacy IS NOT NULL`
- Ordenado por `published_at DESC` (recentes primeiro)

**Verificar quantidade:**
```sql
SELECT COUNT(*) FROM news
WHERE embedding_model_version = 'mpnet'
   OR (content_embedding IS NULL AND content_embedding_legacy IS NOT NULL);
```

---

### Passo 2: Converter CSV → Parquet

**Por quê Parquet?**
- Compressão ~5-10x melhor que CSV
- Leitura ~100x mais rápida
- Preserva tipos de dados

```bash
# Conversão completa
python csv_to_parquet.py /tmp/artigos_para_migrar.csv

# Ou com sample (para testes)
python csv_to_parquet.py /tmp/artigos_para_migrar.csv --sample 1000
```

**Saída:**
```
Reading CSV: /tmp/artigos_para_migrar.csv
  Loaded: 300,000 rows
  Columns: ['id', 'unique_id', 'title', 'summary', 'content', 'published_at']
  Memory: 245.3 MB
Converting to Parquet: artigos_para_migrar.parquet
Done!
  Output size: 42.1 MB
  Compression ratio: 5.8x
  Saved to: artigos_para_migrar.parquet
```

---

### Passo 3: Gerar Embeddings (GPU)

**Opção A: Pipeline Completo (Generate + Upload)**
```bash
python migrate_to_bge_m3.py full \
    --input artigos_para_migrar.parquet \
    --database-url $DATABASE_URL \
    --batch-size 128
```

**Opção B: Passos Separados (mais controle)**

**3.1. Gerar embeddings**
```bash
python migrate_to_bge_m3.py generate \
    --input artigos_para_migrar.parquet \
    --output embeddings_bge_m3.parquet \
    --batch-size 128 \
    --device cuda
```

**Saída esperada:**
```
Initializing migrator...
  Model: BAAI/bge-m3
  Device: cuda
  Batch size: 128
  GPU: NVIDIA L4
  VRAM: 24.0 GB
Loading model BAAI/bge-m3...
Model loaded in 12.3s
  Embedding dimension: 1024
Starting migration...
  Input: artigos_para_migrar.parquet
  Output: embeddings_bge_m3.parquet
Reading dump from artigos_para_migrar.parquet...
Total articles to process: 300,000
Generating embeddings: 100%|████████| 300000/300000 [20:15<00:00, 247.0 articles/s]
Progress: 10,000/300,000 (3.3%) | Rate: 247 articles/s | ETA: 19.5h
Progress: 20,000/300,000 (6.7%) | Rate: 248 articles/s | ETA: 18.8h
...
Migration complete!
  Processed: 300,000 articles
  Errors: 0
  Time: 20.25h
  Rate: 247 articles/s
Saving final results to embeddings_bge_m3.parquet...
Done! Results saved to embeddings_bge_m3.parquet
```

**3.2. Upload para PostgreSQL**
```bash
# Teste primeiro (dry-run)
python migrate_to_bge_m3.py upload \
    --input embeddings_bge_m3.parquet \
    --database-url $DATABASE_URL \
    --dry-run

# Upload real
python migrate_to_bge_m3.py upload \
    --input embeddings_bge_m3.parquet \
    --database-url $DATABASE_URL \
    --batch-size 1000
```

**Saída esperada:**
```
Starting bulk upload to PostgreSQL...
  Input: embeddings_bge_m3.parquet
  Batch size: 1000
  Dry run: False
Loading embeddings...
Total embeddings to upload: 300,000
Connecting to PostgreSQL...
Uploading: 100%|████████| 300000/300000 [15:30<00:00, 322.6 embeddings/s]
Upload complete!
  Uploaded: 300,000 embeddings
  Errors: 0
  Time: 930.2s
  Rate: 323 updates/s
```

---

## ⚙️ Parâmetros e Tunin

### Batch Size (GPU)

**Recomendações por GPU:**

| GPU | VRAM | Batch Size | Throughput |
|-----|------|------------|------------|
| L4 | 24 GB | **128-256** | ~200-300 art/s |
| T4 | 16 GB | 64-128 | ~150-200 art/s |
| V100 | 16 GB | 64-128 | ~200-250 art/s |
| A100 | 40 GB | 256-512 | ~400-600 art/s |

**Ajuste baseado em uso de memória:**
```bash
# Monitorar VRAM durante execução
watch -n 1 nvidia-smi

# Se OOM (out of memory), reduzir batch size
python migrate_to_bge_m3.py generate \
    --batch-size 64  # Reduzir pela metade
```

### Checkpoints

**Por padrão:** checkpoint a cada 10k artigos

**Customizar:**
```bash
python migrate_to_bge_m3.py generate \
    --checkpoint-every 5000  # Checkpoints mais frequentes
```

**Retomar de checkpoint:**
```bash
# Se interrompido, retomar do último checkpoint
python migrate_to_bge_m3.py generate \
    --input artigos_para_migrar.parquet \
    --output embeddings_bge_m3.parquet \
    --resume-from embeddings_bge_m3_checkpoint_10000.parquet
```

### Device Selection

```bash
# Auto-detect (padrão)
python migrate_to_bge_m3.py generate --input ... --output ...

# Forçar GPU
python migrate_to_bge_m3.py generate --device cuda --input ... --output ...

# Forçar CPU (mais lento, mas funciona sem GPU)
python migrate_to_bge_m3.py generate --device cpu --input ... --output ...
```

---

## 🧪 Testes

### Teste com Sample Pequeno (1k artigos)

```bash
# 1. Criar sample
python csv_to_parquet.py /tmp/artigos_para_migrar.csv \
    --sample 1000 \
    --output sample_1k.parquet

# 2. Testar geração
python migrate_to_bge_m3.py generate \
    --input sample_1k.parquet \
    --output sample_1k_embeddings.parquet \
    --batch-size 32

# 3. Testar upload (dry-run)
python migrate_to_bge_m3.py upload \
    --input sample_1k_embeddings.parquet \
    --database-url $DATABASE_URL \
    --dry-run

# 4. Validar no banco
psql $DATABASE_URL -c "
SELECT
    embedding_model_version,
    COUNT(*) as count
FROM news
WHERE unique_id IN (
    SELECT unique_id FROM news
    ORDER BY published_at DESC
    LIMIT 1000
)
GROUP BY embedding_model_version;
"
```

### Validação de Qualidade

```sql
-- Verificar embeddings gerados
SELECT
    id,
    unique_id,
    embedding_model_version,
    array_length(content_embedding, 1) as embedding_dim,
    embedding_generated_at
FROM news
WHERE embedding_model_version = 'bge-m3'
ORDER BY embedding_generated_at DESC
LIMIT 10;

-- Deve retornar dim = 1024
```

---

## 📊 Monitoramento

### Durante Execução

```bash
# Terminal 1: Rodar migração
python migrate_to_bge_m3.py generate ...

# Terminal 2: Monitorar GPU
watch -n 1 nvidia-smi

# Terminal 3: Monitorar logs
tail -f migration.log
```

### Métricas Importantes

**GPU:**
- VRAM usage: < 80% (ideal: 60-70%)
- GPU utilization: > 80%
- Temperature: < 80°C

**Performance:**
- Throughput: 200-300 articles/s (GPU L4)
- Checkpoint saves: < 5s cada
- ETA: ~20h para 300k artigos

**Erros:**
- Error rate: < 0.1%
- Se > 10 erros: script aborta automaticamente

---

## 🔍 Troubleshooting

### Problema: OOM (Out of Memory)

**Sintomas:**
```
RuntimeError: CUDA out of memory
```

**Solução:**
```bash
# Reduzir batch size
--batch-size 64  # ou 32
```

### Problema: Modelo não carrega

**Sintomas:**
```
HuggingFace Hub timeout
```

**Solução:**
```bash
# Pre-download do modelo
python -c "from sentence_transformers import SentenceTransformer; \
           SentenceTransformer('BAAI/bge-m3')"
```

### Problema: Upload lento

**Sintomas:**
- < 100 updates/s

**Solução:**
```bash
# Aumentar batch size de upload
--batch-size 5000

# Verificar latência do banco
psql $DATABASE_URL -c "SELECT pg_stat_activity.* FROM pg_stat_activity;"
```

### Problema: Script interrompido

**Solução:**
```bash
# Retomar do último checkpoint
python migrate_to_bge_m3.py generate \
    --resume-from embeddings_bge_m3_checkpoint_<N>.parquet
```

---

## 📁 Arquivos Gerados

```
scripts/embeddings-migration/
├── migrate_to_bge_m3.py           # Script principal
├── csv_to_parquet.py              # Conversor CSV → Parquet
├── dump_articles_for_migration.sql # SQL para dump
├── README.md                       # Este arquivo
│
# Arquivos gerados durante execução:
├── artigos_para_migrar.csv        # Dump PostgreSQL (grande)
├── artigos_para_migrar.parquet    # Dump em Parquet (comprimido)
├── embeddings_bge_m3.parquet      # Embeddings gerados
├── embeddings_bge_m3_metadata.json # Metadados da migração
├── embeddings_bge_m3_checkpoint_*.parquet # Checkpoints
└── migration.log                   # Logs detalhados
```

---

## 🎯 Estimativas de Tempo e Custo

### Com GPU L4 (24GB VRAM)

| Etapa | Tempo | Throughput |
|-------|-------|------------|
| Dump PostgreSQL | ~5 min | - |
| CSV → Parquet | ~2 min | - |
| **Geração embeddings** | **15-25h** | **200-300 art/s** |
| Upload PostgreSQL | ~15 min | ~300 upd/s |
| **Total** | **~20-30h** | - |

### Com CPU (fallback)

| Etapa | Tempo | Throughput |
|-------|-------|------------|
| Geração embeddings | 500-700h | ~1-2 art/s |
| **Total** | **20-30 dias** | - |

**Conclusão:** GPU é ~500x mais rápido! 🚀

---

## ✅ Checklist de Execução

### Antes de Rodar

- [ ] Migration 004 aplicada no PostgreSQL
- [ ] GPU L4 disponível e funcionando
- [ ] Dependências instaladas (`pip install ...`)
- [ ] Dump do PostgreSQL gerado
- [ ] Teste com sample (1k artigos) OK
- [ ] Backup do banco recente (< 24h)

### Durante Execução

- [ ] Monitorar VRAM (< 80%)
- [ ] Monitorar logs (`tail -f migration.log`)
- [ ] Verificar checkpoints sendo salvos
- [ ] ETA razoável (~20h)

### Após Conclusão

- [ ] 100% artigos processados (verificar no banco)
- [ ] Embeddings dimension = 1024 (verificar)
- [ ] `embedding_model_version = 'bge-m3'` (verificar)
- [ ] Re-indexar Typesense
- [ ] Validar busca semântica funcionando
- [ ] Cleanup arquivos temporários

---

## 📞 Suporte

**Dúvidas ou problemas?**
- Abrir issue: `destaquesgovbr/data-platform#175`
- Logs detalhados em: `migration.log`
- Documentação completa: `PLANO_MIGRACAO_BGE_M3.md` (repo infra)

---

**Autor:** Luis Felipe de Moraes  
**Data:** 2026-06-16  
**Versão:** 1.0
