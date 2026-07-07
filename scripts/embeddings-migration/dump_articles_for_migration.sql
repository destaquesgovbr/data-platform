-- ============================================================================
-- Script para gerar dump de artigos para migração de embeddings
-- De: mpnet-768d → Para: BGE-M3-1024d
-- ============================================================================

-- Verificar quantos artigos precisam migração
SELECT
    embedding_model_version,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM news
WHERE content_embedding_legacy IS NOT NULL
   OR content_embedding IS NOT NULL
GROUP BY embedding_model_version
ORDER BY count DESC;

-- Export para CSV (para testes pequenos)
\copy (
    SELECT
        id,
        unique_id,
        title,
        summary,
        content,
        published_at
    FROM news
    WHERE embedding_model_version = 'mpnet'
       OR (content_embedding IS NULL AND content_embedding_legacy IS NOT NULL)
    ORDER BY published_at DESC
) TO '/tmp/artigos_para_migrar.csv' WITH (FORMAT CSV, HEADER true);

-- Para Parquet (mais eficiente, recomendado):
-- Não é possível exportar diretamente para Parquet do psql
-- Use Python após export CSV:
--
-- import pandas as pd
-- df = pd.read_csv('/tmp/artigos_para_migrar.csv')
-- df.to_parquet('artigos_para_migrar.parquet', index=False)
-- print(f"Exported {len(df):,} articles")

-- Estatísticas do dump
SELECT
    'Total articles needing migration' as metric,
    COUNT(*) as value
FROM news
WHERE embedding_model_version = 'mpnet'
   OR (content_embedding IS NULL AND content_embedding_legacy IS NOT NULL)
UNION ALL
SELECT
    'Already migrated (bge-m3)' as metric,
    COUNT(*) as value
FROM news
WHERE embedding_model_version = 'bge-m3'
UNION ALL
SELECT
    'Migration progress (%)' as metric,
    ROUND(
        COUNT(*) FILTER (WHERE embedding_model_version = 'bge-m3') * 100.0 /
        NULLIF(COUNT(*) FILTER (WHERE content_embedding IS NOT NULL OR content_embedding_legacy IS NOT NULL), 0),
        2
    ) as value
FROM news;
