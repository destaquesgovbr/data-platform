-- Migration 003: Create HNSW indexes for vector similarity search
-- Phase 4.7: Embeddings Semânticos
-- Created: 2024-12-26

-- HNSW index for fast cosine similarity search
-- Parameters: m=16 (connections per layer), ef_construction=64 (search width during construction)
-- These are balanced defaults for good performance vs build time
CREATE INDEX IF NOT EXISTS idx_news_content_embedding_hnsw
ON news USING hnsw (content_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- Index for finding records without embeddings (for incremental generation)
CREATE INDEX IF NOT EXISTS idx_news_embedding_status
ON news (embedding_generated_at)
WHERE content_embedding IS NULL;

-- Index for incremental sync (recently updated embeddings)
CREATE INDEX IF NOT EXISTS idx_news_embedding_updated
ON news (embedding_generated_at DESC)
WHERE content_embedding IS NOT NULL;

-- Index for 2025 news filtering (our target scope)
CREATE INDEX IF NOT EXISTS idx_news_published_at_2025
ON news (published_at)
WHERE published_at >= '2025-01-01' AND published_at < '2026-01-01';

-- Verify indexes were created
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'news'
  AND indexname LIKE '%embedding%'
ORDER BY indexname;
