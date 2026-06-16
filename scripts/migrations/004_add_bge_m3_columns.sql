-- Migration 004: Add BGE-M3 embedding column and model version tracking
-- Migration from mpnet-768d to BGE-M3-1024d
-- Created: 2026-06-16
-- Related: data-science#1, data-platform#175

-- Step 1: Rename existing embedding column to preserve legacy data
ALTER TABLE news
RENAME COLUMN content_embedding TO content_embedding_legacy;

-- Step 2: Add new column for BGE-M3 embeddings (1024 dimensions)
ALTER TABLE news
ADD COLUMN IF NOT EXISTS content_embedding vector(1024);

-- Step 3: Add model version tracking column
ALTER TABLE news
ADD COLUMN IF NOT EXISTS embedding_model_version text DEFAULT 'mpnet';

-- Step 4: Update existing records to mark legacy embeddings
UPDATE news
SET embedding_model_version = 'mpnet'
WHERE content_embedding_legacy IS NOT NULL
  AND embedding_model_version IS NULL;

-- Step 5: Create HNSW index for new BGE-M3 embeddings
-- Parameters: m=16 (connections per layer), ef_construction=64 (search width during construction)
CREATE INDEX IF NOT EXISTS idx_news_content_embedding_bge_hnsw
ON news USING hnsw (content_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Step 6: Update index for finding records needing migration
-- This index helps the migration DAG efficiently find articles with legacy embeddings
DROP INDEX IF EXISTS idx_news_embedding_status;
CREATE INDEX idx_news_embedding_status_migration
ON news (embedding_model_version, published_at DESC)
WHERE content_embedding IS NULL OR embedding_model_version = 'mpnet';

-- Step 7: Add comments for documentation
COMMENT ON COLUMN news.content_embedding_legacy IS
    'Legacy embedding (768-dim) from paraphrase-multilingual-mpnet-base-v2 model. Will be removed after migration to BGE-M3 is complete (data-platform#175).';

COMMENT ON COLUMN news.content_embedding IS
    'Semantic embedding (1024-dim) from BAAI/bge-m3 model. Primary embedding field for semantic search. Validated in data-science#1.';

COMMENT ON COLUMN news.embedding_model_version IS
    'Embedding model version: "mpnet" (legacy 768-dim) or "bge-m3" (current 1024-dim). Used to track migration progress and determine which embedding to use.';

-- Step 8: Verify migration applied correctly
DO $$
DECLARE
    v_legacy_col_exists boolean;
    v_new_col_exists boolean;
    v_version_col_exists boolean;
    v_index_exists boolean;
    v_legacy_count bigint;
    v_bge_count bigint;
    v_total_with_embedding bigint;
BEGIN
    -- Check columns exist
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'content_embedding_legacy'
    ) INTO v_legacy_col_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'content_embedding'
    ) INTO v_new_col_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'embedding_model_version'
    ) INTO v_version_col_exists;

    -- Check index exists
    SELECT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'news' AND indexname = 'idx_news_content_embedding_bge_hnsw'
    ) INTO v_index_exists;

    -- Get migration stats
    SELECT COUNT(*) FROM news
    WHERE content_embedding_legacy IS NOT NULL OR content_embedding IS NOT NULL
    INTO v_total_with_embedding;

    SELECT COUNT(*) FROM news WHERE embedding_model_version = 'mpnet' INTO v_legacy_count;
    SELECT COUNT(*) FROM news WHERE embedding_model_version = 'bge-m3' INTO v_bge_count;

    -- Report results
    RAISE NOTICE '=== Migration 004: BGE-M3 Columns - Verification ===';
    RAISE NOTICE 'Column content_embedding_legacy exists: %', v_legacy_col_exists;
    RAISE NOTICE 'Column content_embedding (1024d) exists: %', v_new_col_exists;
    RAISE NOTICE 'Column embedding_model_version exists: %', v_version_col_exists;
    RAISE NOTICE 'Index idx_news_content_embedding_bge_hnsw exists: %', v_index_exists;
    RAISE NOTICE '';
    RAISE NOTICE 'Migration Stats:';
    RAISE NOTICE '  Total articles with embeddings: %', v_total_with_embedding;
    RAISE NOTICE '  Legacy (mpnet-768d): %', v_legacy_count;
    RAISE NOTICE '  Current (bge-m3-1024d): %', v_bge_count;
    RAISE NOTICE '  Migration progress: %% (% / %)',
        CASE WHEN v_total_with_embedding > 0
             THEN ROUND((v_bge_count::numeric / v_total_with_embedding::numeric) * 100, 2)
             ELSE 0
        END,
        v_bge_count,
        v_total_with_embedding;

    -- Fail if critical columns missing
    IF NOT (v_legacy_col_exists AND v_new_col_exists AND v_version_col_exists) THEN
        RAISE EXCEPTION 'Migration 004 failed: Required columns not created';
    END IF;

    -- Fail if index missing
    IF NOT v_index_exists THEN
        RAISE EXCEPTION 'Migration 004 failed: HNSW index not created';
    END IF;

    RAISE NOTICE '=== Migration 004 completed successfully ===';
END $$;

-- Step 9: Show sample of data for manual verification
SELECT
    id,
    unique_id,
    embedding_model_version,
    CASE WHEN content_embedding_legacy IS NOT NULL THEN 'YES' ELSE 'NO' END as has_legacy,
    CASE WHEN content_embedding IS NOT NULL THEN 'YES' ELSE 'NO' END as has_bge,
    embedding_generated_at
FROM news
WHERE content_embedding_legacy IS NOT NULL OR content_embedding IS NOT NULL
ORDER BY embedding_generated_at DESC NULLS LAST
LIMIT 5;
