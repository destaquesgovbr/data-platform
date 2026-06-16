-- Rollback for Migration 004: Remove BGE-M3 columns and restore original schema
-- WARNING: This will DELETE all BGE-M3 embeddings (1024-dim)
-- Only run this if migration needs to be reverted BEFORE cleanup phase
-- Created: 2026-06-16

-- Confirm rollback intention
DO $$
BEGIN
    RAISE NOTICE '=== WARNING: Migration 004 Rollback ===';
    RAISE NOTICE 'This will:';
    RAISE NOTICE '  1. DELETE all BGE-M3 embeddings (1024-dim)';
    RAISE NOTICE '  2. Restore legacy embedding column name';
    RAISE NOTICE '  3. Remove model version tracking';
    RAISE NOTICE '';
    RAISE NOTICE 'Press Ctrl+C within 5 seconds to cancel...';
    PERFORM pg_sleep(5);
    RAISE NOTICE 'Proceeding with rollback...';
END $$;

-- Step 1: Drop new column (BGE-M3 embeddings)
ALTER TABLE news DROP COLUMN IF EXISTS content_embedding CASCADE;

-- Step 2: Drop model version tracking column
ALTER TABLE news DROP COLUMN IF EXISTS embedding_model_version CASCADE;

-- Step 3: Rename legacy column back to original name
ALTER TABLE news
RENAME COLUMN content_embedding_legacy TO content_embedding;

-- Step 4: Drop new indexes
DROP INDEX IF EXISTS idx_news_content_embedding_bge_hnsw;
DROP INDEX IF EXISTS idx_news_embedding_status_migration;

-- Step 5: Recreate original index for legacy embeddings (if it doesn't exist)
CREATE INDEX IF NOT EXISTS idx_news_content_embedding_hnsw
ON news USING hnsw (content_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Step 6: Recreate original status index
CREATE INDEX IF NOT EXISTS idx_news_embedding_status
ON news (embedding_generated_at)
WHERE content_embedding IS NULL;

CREATE INDEX IF NOT EXISTS idx_news_embedding_updated
ON news (embedding_generated_at DESC)
WHERE content_embedding IS NOT NULL;

-- Step 7: Update comment to original
COMMENT ON COLUMN news.content_embedding IS
    'Semantic embedding (768-dim) from paraphrase-multilingual-mpnet-base-v2 model. Generated from title + summary (Phase 4.7)';

-- Step 8: Verify rollback completed
DO $$
DECLARE
    v_original_col_exists boolean;
    v_bge_col_exists boolean;
    v_version_col_exists boolean;
    v_embedding_count bigint;
BEGIN
    -- Check columns
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'content_embedding'
    ) INTO v_original_col_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'content_embedding_legacy'
    ) INTO v_bge_col_exists;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news' AND column_name = 'embedding_model_version'
    ) INTO v_version_col_exists;

    -- Count embeddings
    SELECT COUNT(*) FROM news WHERE content_embedding IS NOT NULL INTO v_embedding_count;

    -- Report results
    RAISE NOTICE '=== Migration 004 Rollback - Verification ===';
    RAISE NOTICE 'Original column (content_embedding) exists: %', v_original_col_exists;
    RAISE NOTICE 'BGE column removed: %', NOT v_bge_col_exists;
    RAISE NOTICE 'Version column removed: %', NOT v_version_col_exists;
    RAISE NOTICE 'Embeddings preserved: %', v_embedding_count;

    -- Fail if rollback incomplete
    IF NOT v_original_col_exists OR v_bge_col_exists OR v_version_col_exists THEN
        RAISE EXCEPTION 'Rollback failed: Schema not restored correctly';
    END IF;

    RAISE NOTICE '=== Rollback completed successfully ===';
    RAISE NOTICE 'Schema restored to pre-migration state';
END $$;
