-- Initial database setup for local PostgreSQL
--
-- This script runs automatically when the PostgreSQL container is first created
-- via docker-entrypoint-initdb.d
--

-- Agencies table
CREATE TABLE IF NOT EXISTS agencies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100),
    parent_key VARCHAR(100),
    url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_parent_agency
        FOREIGN KEY (parent_key) REFERENCES agencies(key) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agencies_key ON agencies(key);
CREATE INDEX IF NOT EXISTS idx_agencies_parent ON agencies(parent_key);

-- Themes table
CREATE TABLE IF NOT EXISTS themes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    label VARCHAR(500) NOT NULL,
    full_name VARCHAR(600),
    level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_parent_theme
        FOREIGN KEY (parent_code) REFERENCES themes(code) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_themes_code ON themes(code);
CREATE INDEX IF NOT EXISTS idx_themes_level ON themes(level);
CREATE INDEX IF NOT EXISTS idx_themes_parent ON themes(parent_code);

-- News table
CREATE TABLE IF NOT EXISTS news (
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

    -- AI-generated
    summary TEXT,

    -- Timestamps
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime TIMESTAMP WITH TIME ZONE,
    extracted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    synced_to_hf_at TIMESTAMP WITH TIME ZONE,

    -- Denormalized (performance)
    agency_key VARCHAR(100),
    agency_name VARCHAR(500)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_news_unique_id ON news(unique_id);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_agency_id ON news(agency_id);
CREATE INDEX IF NOT EXISTS idx_news_most_specific_theme ON news(most_specific_theme_id);
CREATE INDEX IF NOT EXISTS idx_news_agency_key ON news(agency_key);
CREATE INDEX IF NOT EXISTS idx_news_agency_date ON news(agency_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_synced_to_hf ON news(synced_to_hf_at) WHERE synced_to_hf_at IS NULL;

-- Trigger to update updated_at automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
