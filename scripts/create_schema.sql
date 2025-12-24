-- GovBRNews PostgreSQL Schema
-- Version: 1.0
-- Database: govbrnews
-- Encoding: UTF-8
-- Timezone: UTC
--
-- Migration from HuggingFace Dataset to Cloud SQL PostgreSQL
-- This schema supports ~300k news records with normalized agencies and themes

-- =============================================================================
-- TABLE: agencies
-- =============================================================================
-- Stores master data for government agencies (~158 records)

CREATE TABLE agencies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100),
    parent_key VARCHAR(100),
    url VARCHAR(1000),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE agencies IS 'Government agencies master data';
COMMENT ON COLUMN agencies.key IS 'Unique agency identifier (e.g., "mec", "saude")';
COMMENT ON COLUMN agencies.name IS 'Full agency name';
COMMENT ON COLUMN agencies.type IS 'Agency type (Ministério, Agência, etc.)';
COMMENT ON COLUMN agencies.parent_key IS 'Parent agency reference';
COMMENT ON COLUMN agencies.url IS 'RSS feed URL';

-- Indexes for agencies
CREATE INDEX idx_agencies_key ON agencies(key);
CREATE INDEX idx_agencies_parent ON agencies(parent_key);

-- =============================================================================
-- TABLE: themes
-- =============================================================================
-- Hierarchical taxonomy with 3 levels (L1 → L2 → L3)
-- Total: ~150-200 themes (25 L1, ~100 L2, ~50-75 L3)

CREATE TABLE themes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    label VARCHAR(500) NOT NULL,
    full_name VARCHAR(600),
    level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_parent_theme FOREIGN KEY (parent_code)
        REFERENCES themes(code) ON DELETE SET NULL
);

COMMENT ON TABLE themes IS 'Hierarchical theme taxonomy (3 levels)';
COMMENT ON COLUMN themes.code IS 'Hierarchical code (e.g., "01.01.01")';
COMMENT ON COLUMN themes.label IS 'Theme name';
COMMENT ON COLUMN themes.full_name IS 'Code + label combined';
COMMENT ON COLUMN themes.level IS 'Hierarchy level (1, 2, or 3)';
COMMENT ON COLUMN themes.parent_code IS 'Parent theme code';

-- Indexes for themes
CREATE INDEX idx_themes_code ON themes(code);
CREATE INDEX idx_themes_level ON themes(level);
CREATE INDEX idx_themes_parent ON themes(parent_code);

-- =============================================================================
-- TABLE: news
-- =============================================================================
-- Main news storage (~300k records)
-- Partially normalized: FKs to agencies/themes + denormalized agency fields

CREATE TABLE news (
    id SERIAL PRIMARY KEY,
    unique_id VARCHAR(32) UNIQUE NOT NULL,

    -- Foreign keys
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    theme_l1_id INTEGER REFERENCES themes(id),
    theme_l2_id INTEGER REFERENCES themes(id),
    theme_l3_id INTEGER REFERENCES themes(id),
    most_specific_theme_id INTEGER REFERENCES themes(id),

    -- Core content
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    category VARCHAR(500),
    tags TEXT[],
    content TEXT,
    editorial_lead TEXT,
    subtitle TEXT,

    -- AI-generated content (via Cogfy)
    summary TEXT,

    -- Timestamps
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime TIMESTAMP WITH TIME ZONE,
    extracted_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    synced_to_hf_at TIMESTAMP WITH TIME ZONE,

    -- Denormalized fields (for query performance)
    agency_key VARCHAR(100),
    agency_name VARCHAR(500)
);

COMMENT ON TABLE news IS 'Main news storage (migrated from HuggingFace Dataset)';
COMMENT ON COLUMN news.unique_id IS 'MD5(agency + published_at + title)';
COMMENT ON COLUMN news.most_specific_theme_id IS 'Most granular theme (L3 > L2 > L1)';
COMMENT ON COLUMN news.summary IS 'AI-generated summary from Cogfy';
COMMENT ON COLUMN news.synced_to_hf_at IS 'Last sync to HuggingFace Dataset';
COMMENT ON COLUMN news.agency_key IS 'Denormalized agency.key for performance';
COMMENT ON COLUMN news.agency_name IS 'Denormalized agency.name for performance';

-- Primary lookup index
CREATE UNIQUE INDEX idx_news_unique_id ON news(unique_id);

-- Date queries (most common access pattern)
CREATE INDEX idx_news_published_at ON news(published_at DESC);
CREATE INDEX idx_news_published_date ON news(DATE(published_at));

-- Agency filtering
CREATE INDEX idx_news_agency_id ON news(agency_id);
CREATE INDEX idx_news_agency_key ON news(agency_key);

-- Theme filtering
CREATE INDEX idx_news_theme_l1 ON news(theme_l1_id);
CREATE INDEX idx_news_most_specific_theme ON news(most_specific_theme_id);

-- Sync tracking (partial index for unsync'd records)
CREATE INDEX idx_news_synced_to_hf ON news(synced_to_hf_at)
    WHERE synced_to_hf_at IS NULL;

-- Composite indexes for common query patterns
CREATE INDEX idx_news_agency_date ON news(agency_id, published_at DESC);
CREATE INDEX idx_news_date_range ON news(published_at)
    WHERE published_at >= NOW() - INTERVAL '1 year';

-- Full-text search (PostgreSQL Portuguese support)
CREATE INDEX idx_news_fts ON news
    USING GIN (to_tsvector('portuguese', title || ' ' || COALESCE(content, '')));

-- =============================================================================
-- TABLE: sync_log
-- =============================================================================
-- Tracks sync operations (HuggingFace, Typesense, etc.)

CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    operation VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_processed INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    metadata JSONB
);

COMMENT ON TABLE sync_log IS 'Sync operation tracking (HF, Typesense, Qdrant)';
COMMENT ON COLUMN sync_log.operation IS 'Operation type (e.g., hf_export, typesense_index)';
COMMENT ON COLUMN sync_log.status IS 'Status: started, completed, failed';
COMMENT ON COLUMN sync_log.metadata IS 'Additional operation data (batch_size, etc.)';

-- Index for sync_log queries
CREATE INDEX idx_sync_log_operation ON sync_log(operation, started_at DESC);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Trigger function: Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to news table
CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Apply trigger to agencies table
CREATE TRIGGER update_agencies_updated_at
    BEFORE UPDATE ON agencies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger function: Denormalize agency info into news
CREATE OR REPLACE FUNCTION denormalize_agency_info()
RETURNS TRIGGER AS $$
BEGIN
    SELECT key, name INTO NEW.agency_key, NEW.agency_name
    FROM agencies WHERE id = NEW.agency_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply denormalization trigger to news
CREATE TRIGGER denormalize_news_agency
    BEFORE INSERT OR UPDATE OF agency_id ON news
    FOR EACH ROW
    EXECUTE FUNCTION denormalize_agency_info();

-- =============================================================================
-- HELPER VIEWS
-- =============================================================================

-- View: News with full theme hierarchy
CREATE VIEW news_with_themes AS
SELECT
    n.id,
    n.unique_id,
    n.title,
    n.url,
    n.agency_name,
    n.published_at,
    n.summary,
    t1.label as theme_l1,
    t2.label as theme_l2,
    t3.label as theme_l3,
    COALESCE(t3.label, t2.label, t1.label) as most_specific_theme
FROM news n
LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
LEFT JOIN themes t3 ON n.theme_l3_id = t3.id;

COMMENT ON VIEW news_with_themes IS 'News with denormalized theme hierarchy for easy querying';

-- View: Recent sync operations
CREATE VIEW recent_syncs AS
SELECT
    operation,
    status,
    records_processed,
    records_failed,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_seconds,
    error_message
FROM sync_log
ORDER BY started_at DESC
LIMIT 100;

COMMENT ON VIEW recent_syncs IS 'Last 100 sync operations with duration';

-- =============================================================================
-- INITIAL DATA VALIDATION
-- =============================================================================

-- Validation query: Check schema creation
DO $$
DECLARE
    table_count INTEGER;
    index_count INTEGER;
    trigger_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO table_count FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

    SELECT COUNT(*) INTO index_count FROM pg_indexes
    WHERE schemaname = 'public';

    SELECT COUNT(*) INTO trigger_count FROM information_schema.triggers
    WHERE trigger_schema = 'public';

    RAISE NOTICE 'Schema creation completed successfully:';
    RAISE NOTICE '  Tables: %', table_count;
    RAISE NOTICE '  Indexes: %', index_count;
    RAISE NOTICE '  Triggers: %', trigger_count;

    IF table_count < 4 THEN
        RAISE EXCEPTION 'Expected at least 4 tables, got %', table_count;
    END IF;
END $$;

-- =============================================================================
-- SCHEMA VERSION TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(20) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_version (version, description)
VALUES ('1.0', 'Initial schema for GovBRNews data platform migration');

-- =============================================================================
-- COMPLETION MESSAGE
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'GovBRNews Schema v1.0 - READY';
    RAISE NOTICE '========================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Run: python scripts/populate_agencies.py';
    RAISE NOTICE '2. Run: python scripts/populate_themes.py';
    RAISE NOTICE '3. Run: python scripts/migrate_hf_to_postgres.py';
    RAISE NOTICE '';
END $$;
