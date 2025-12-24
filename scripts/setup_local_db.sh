#!/bin/bash
#
# Setup local PostgreSQL database for development
#
# This script:
# 1. Waits for PostgreSQL to be ready
# 2. Creates database schema
# 3. Populates agencies table
# 4. Populates themes table
#
# Usage:
#   ./scripts/setup_local_db.sh
#   ./scripts/setup_local_db.sh --reset  # Drop and recreate everything
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env.local if exists
if [ -f "$PROJECT_ROOT/.env.local" ]; then
    echo -e "${GREEN}Loading .env.local${NC}"
    export $(cat "$PROJECT_ROOT/.env.local" | grep -v '^#' | xargs)
fi

# Database connection parameters
DB_USER=${POSTGRES_USER:-govbrnews_dev}
DB_PASS=${POSTGRES_PASSWORD:-dev_password}
DB_NAME=${POSTGRES_DB:-govbrnews_dev}
DB_HOST=${POSTGRES_HOST:-localhost}
DB_PORT=${POSTGRES_PORT:-5432}

DB_URL="postgresql://${DB_USER}:${DB_PASS}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

# Parse arguments
RESET=false
if [ "$1" == "--reset" ]; then
    RESET=true
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup Local Database${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Function to check if PostgreSQL is ready
wait_for_postgres() {
    echo -e "${YELLOW}Waiting for PostgreSQL to be ready...${NC}"

    max_attempts=30
    attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if docker exec destaquesgovbr-postgres pg_isready -U "$DB_USER" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
            return 0
        fi

        attempt=$((attempt + 1))
        echo -n "."
        sleep 1
    done

    echo -e "${RED}✗ PostgreSQL did not become ready in time${NC}"
    exit 1
}

# Function to execute SQL file
execute_sql_file() {
    local sql_file=$1
    echo -e "${YELLOW}Executing ${sql_file}...${NC}"

    docker exec -i destaquesgovbr-postgres psql -U "$DB_USER" -d "$DB_NAME" < "$sql_file"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ ${sql_file} executed successfully${NC}"
    else
        echo -e "${RED}✗ Failed to execute ${sql_file}${NC}"
        exit 1
    fi
}

# Wait for PostgreSQL
wait_for_postgres

# Reset if requested
if [ "$RESET" = true ]; then
    echo -e "${YELLOW}Resetting database...${NC}"

    docker exec destaquesgovbr-postgres psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};" || true
    docker exec destaquesgovbr-postgres psql -U "$DB_USER" -d postgres -c "CREATE DATABASE ${DB_NAME};"

    echo -e "${GREEN}✓ Database reset${NC}"
fi

# Create schema
echo -e "${YELLOW}Creating schema...${NC}"

SQL_FILE="$SCRIPT_DIR/../_plan/SCHEMA.sql"
if [ ! -f "$SQL_FILE" ]; then
    # Create schema SQL if not exists
    cat > /tmp/create_schema.sql <<'EOF'
-- Create agencies table
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

-- Create themes table
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

-- Create news table
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

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_news_updated_at BEFORE UPDATE ON news
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
EOF

    docker exec -i destaquesgovbr-postgres psql -U "$DB_USER" -d "$DB_NAME" < /tmp/create_schema.sql
    rm /tmp/create_schema.sql
else
    execute_sql_file "$SQL_FILE"
fi

echo -e "${GREEN}✓ Schema created${NC}"

# Activate virtual environment and populate tables
echo -e "${YELLOW}Populating tables...${NC}"

cd "$PROJECT_ROOT"

# Find Python virtual environment
if [ -f "/Users/nitai/Library/Caches/pypoetry/virtualenvs/govbr-news-ai-_H0Lmpg7-py3.13/bin/activate" ]; then
    source "/Users/nitai/Library/Caches/pypoetry/virtualenvs/govbr-news-ai-_H0Lmpg7-py3.13/bin/activate"
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set environment variable for local database
export DATABASE_URL="$DB_URL"

# Populate agencies
echo -e "${YELLOW}Populating agencies...${NC}"
python scripts/populate_agencies.py

# Populate themes
echo -e "${YELLOW}Populating themes...${NC}"
python scripts/populate_themes.py

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Local database setup complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Connection string:"
echo -e "  ${DB_URL}"
echo ""
echo -e "To connect with psql:"
echo -e "  ${YELLOW}docker exec -it destaquesgovbr-postgres psql -U ${DB_USER} -d ${DB_NAME}${NC}"
echo ""
echo -e "To test connection:"
echo -e "  ${YELLOW}PYTHONPATH=src python -c \"from data_platform.managers import PostgresManager; m = PostgresManager(connection_string='${DB_URL}'); m.load_cache(); print(f'Agencies: {len(m._agencies_by_key)}, Themes: {len(m._themes_by_code)}')\"${NC}"
echo ""
