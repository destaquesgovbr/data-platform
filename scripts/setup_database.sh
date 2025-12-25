#!/bin/bash
# Setup DestaquesGovBR PostgreSQL Database
# Connects via Cloud SQL Proxy and creates the schema

set -e  # Exit on any error

# Configuration
PROJECT_ID="inspire-7-finep"
REGION="southamerica-east1"
INSTANCE_NAME="destaquesgovbr-postgres"
DATABASE="destaquesgovbr"
USER="destaquesgovbr_app"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}DestaquesGovBR Database Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if cloud-sql-proxy is installed
if ! command -v cloud-sql-proxy &> /dev/null; then
    echo -e "${RED}Error: cloud-sql-proxy not found${NC}"
    echo "Install it with:"
    echo "  brew install cloud-sql-proxy  # macOS"
    echo "  or download from: https://cloud.google.com/sql/docs/postgres/connect-instance-auth-proxy"
    exit 1
fi

# Check if psql is installed
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql not found${NC}"
    echo "Install PostgreSQL client:"
    echo "  brew install postgresql  # macOS"
    echo "  apt-get install postgresql-client  # Ubuntu"
    exit 1
fi

echo -e "${YELLOW}Step 1: Fetching database credentials...${NC}"
PASSWORD=$(gcloud secrets versions access latest --secret="destaquesgovbr-postgres-password" 2>/dev/null)
if [ -z "$PASSWORD" ]; then
    echo -e "${RED}Error: Could not fetch password from Secret Manager${NC}"
    echo "Make sure you're authenticated with gcloud and have access to the secret"
    exit 1
fi
echo -e "${GREEN}✓ Password retrieved${NC}"
echo ""

echo -e "${YELLOW}Step 2: Starting Cloud SQL Proxy...${NC}"
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${INSTANCE_NAME}"
echo "Connection: $CONNECTION_NAME"

# Start proxy in background
cloud-sql-proxy $CONNECTION_NAME --port=5432 &
PROXY_PID=$!

# Cleanup function to kill proxy on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Stopping Cloud SQL Proxy...${NC}"
    kill $PROXY_PID 2>/dev/null || true
    wait $PROXY_PID 2>/dev/null || true
    echo -e "${GREEN}✓ Proxy stopped${NC}"
}
trap cleanup EXIT

# Wait for proxy to be ready
echo "Waiting for proxy to start..."
sleep 3
echo -e "${GREEN}✓ Proxy started (PID: $PROXY_PID)${NC}"
echo ""

echo -e "${YELLOW}Step 3: Testing database connection...${NC}"
export PGPASSWORD=$PASSWORD
if psql -h 127.0.0.1 -U $USER -d $DATABASE -c "SELECT version();" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Connection successful${NC}"
else
    echo -e "${RED}Error: Could not connect to database${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}Step 4: Checking current database state...${NC}"
TABLE_COUNT=$(psql -h 127.0.0.1 -U $USER -d $DATABASE -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" | xargs)
echo "Current tables in database: $TABLE_COUNT"

if [ "$TABLE_COUNT" -gt "0" ]; then
    echo -e "${YELLOW}⚠ Database already has tables${NC}"
    read -p "Do you want to drop existing tables and recreate schema? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo "Aborted"
        exit 0
    fi
    echo -e "${YELLOW}Dropping existing tables...${NC}"
    psql -h 127.0.0.1 -U $USER -d $DATABASE -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    echo -e "${GREEN}✓ Tables dropped${NC}"
fi
echo ""

echo -e "${YELLOW}Step 5: Creating database schema...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_FILE="$SCRIPT_DIR/create_schema.sql"

if [ ! -f "$SCHEMA_FILE" ]; then
    echo -e "${RED}Error: Schema file not found: $SCHEMA_FILE${NC}"
    exit 1
fi

echo "Running: $SCHEMA_FILE"
if psql -h 127.0.0.1 -U $USER -d $DATABASE -f "$SCHEMA_FILE"; then
    echo -e "${GREEN}✓ Schema created successfully${NC}"
else
    echo -e "${RED}Error: Schema creation failed${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}Step 6: Verifying schema...${NC}"
psql -h 127.0.0.1 -U $USER -d $DATABASE << 'EOF'
\echo 'Tables:'
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

\echo ''
\echo 'Views:'
SELECT viewname FROM pg_views WHERE schemaname = 'public' ORDER BY viewname;

\echo ''
\echo 'Indexes count:'
SELECT COUNT(*) as index_count FROM pg_indexes WHERE schemaname = 'public';

\echo ''
\echo 'Schema version:'
SELECT * FROM schema_version;
EOF
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Database Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "1. Populate agencies: python scripts/populate_agencies.py"
echo "2. Populate themes: python scripts/populate_themes.py"
echo "3. Migrate data: python scripts/migrate_hf_to_postgres.py"
echo ""
echo -e "${BLUE}Connection details:${NC}"
echo "  Host: 127.0.0.1 (via Cloud SQL Proxy)"
echo "  Port: 5432"
echo "  Database: $DATABASE"
echo "  User: $USER"
echo ""
echo -e "${YELLOW}To connect manually:${NC}"
echo "  PGPASSWORD=\$(gcloud secrets versions access latest --secret=\"destaquesgovbr-postgres-password\")"
echo "  cloud-sql-proxy $CONNECTION_NAME &"
echo "  psql -h 127.0.0.1 -U $USER -d $DATABASE"
echo ""
