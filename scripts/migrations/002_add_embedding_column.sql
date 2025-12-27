-- Migration 002: Add embedding columns to news table
-- Phase 4.7: Embeddings Semânticos
-- Created: 2024-12-26

-- Add embedding column (768 dimensions for paraphrase-multilingual-mpnet-base-v2)
ALTER TABLE news
ADD COLUMN IF NOT EXISTS content_embedding vector(768);

-- Add timestamp to track when embedding was generated
ALTER TABLE news
ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP WITH TIME ZONE;

-- Add comments for documentation
COMMENT ON COLUMN news.content_embedding IS
    'Semantic embedding (768-dim) from paraphrase-multilingual-mpnet-base-v2 model. Generated from title + summary (Phase 4.7)';

COMMENT ON COLUMN news.embedding_generated_at IS
    'Timestamp when embedding was last generated (Phase 4.7)';

-- Verify columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'news'
  AND column_name IN ('content_embedding', 'embedding_generated_at')
ORDER BY column_name;
