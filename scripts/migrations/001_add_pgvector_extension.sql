-- Migration 001: Enable pgvector extension for vector similarity search
-- Phase 4.7: Embeddings Semânticos
-- Created: 2024-12-26

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension is enabled
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'Failed to enable pgvector extension';
    END IF;
    RAISE NOTICE 'pgvector extension enabled successfully';
END $$;

-- Display version
SELECT extversion FROM pg_extension WHERE extname = 'vector';
