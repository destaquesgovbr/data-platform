# Database Setup and Migrations

Quick guide for setting up and managing the PostgreSQL database.

---

## Initial Setup

### Prerequisites

```bash
# Install Cloud SQL Proxy
brew install cloud-sql-proxy  # macOS
# or download from: https://cloud.google.com/sql/docs/postgres/connect-instance-auth-proxy

# Install PostgreSQL client
brew install postgresql@15  # macOS
```

### 1. Create Database Schema

Run the automated setup script:

```bash
cd /path/to/data-platform
./scripts/setup_database.sh
```

This script will:
1. Check prerequisites (cloud-sql-proxy, psql)
2. Fetch credentials from Secret Manager
3. Start Cloud SQL Proxy
4. Connect to database
5. Create schema (tables, indexes, triggers, views)
6. Validate structure

**Expected output**:
```
✅ Cloud SQL Proxy running on port 5432
✅ Connected to PostgreSQL 15.15
✅ Creating schema...
NOTICE: Schema creation completed successfully:
  Tables: 5
  Indexes: 22
  Triggers: 4
✅ Schema created successfully
```

### 2. Verify Schema

Connect to the database:

```bash
# Get password
PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

# Connect via Cloud SQL Proxy
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &
psql "host=127.0.0.1 dbname=govbrnews user=govbrnews_app password=$PASSWORD"
```

Check tables:

```sql
-- List all tables
\dt

-- Check table structure
\d news
\d agencies
\d themes

-- Count records
SELECT
    (SELECT COUNT(*) FROM agencies) as agencies,
    (SELECT COUNT(*) FROM themes) as themes,
    (SELECT COUNT(*) FROM news) as news,
    (SELECT COUNT(*) FROM sync_log) as sync_log;
```

---

## Populate Master Data

### 1. Agencies

Populate the `agencies` table from the agencies YAML file:

```bash
python scripts/populate_agencies.py
```

**Expected**: ~158 agency records

### 2. Themes

Populate the `themes` table from the themes taxonomy file:

```bash
python scripts/populate_themes.py
```

**Expected**: ~150-200 theme records (hierarchical: L1 → L2 → L3)

### 3. Verify

```sql
-- Check agencies
SELECT COUNT(*), COUNT(DISTINCT key) FROM agencies;

-- Check themes by level
SELECT level, COUNT(*) FROM themes GROUP BY level ORDER BY level;

-- Sample data
SELECT * FROM agencies LIMIT 5;
SELECT code, label, level FROM themes WHERE level = 1 ORDER BY code;
```

---

## Schema Migrations

### Current Schema Version

```sql
SELECT * FROM schema_version;
```

Expected output:
```
 version |         applied_at         |                description
---------+----------------------------+-------------------------------------------
 1.0     | 2024-12-24 14:XX:XX+00     | Initial schema for GovBRNews data platform
```

### Future Migrations

When creating schema changes:

1. **Create migration SQL file**:
   ```bash
   scripts/migrations/v1.1_add_column.sql
   ```

2. **Apply migration**:
   ```bash
   psql -h 127.0.0.1 -U govbrnews_app -d govbrnews -f scripts/migrations/v1.1_add_column.sql
   ```

3. **Update schema_version**:
   ```sql
   INSERT INTO schema_version (version, description)
   VALUES ('1.1', 'Add new column to news table');
   ```

4. **Document in PROGRESS.md**

---

## Common Operations

### Backup Database

```bash
# Export to Cloud Storage
gcloud sql export sql destaquesgovbr-postgres \
  gs://destaquesgovbr-backups/manual-backup-$(date +%Y%m%d).sql \
  --database=govbrnews
```

### Import Data

```bash
# Import from Cloud Storage
gcloud sql import sql destaquesgovbr-postgres \
  gs://destaquesgovbr-backups/backup.sql \
  --database=govbrnews
```

### Truncate Tables (Development Only)

```sql
-- ⚠️ DANGER: Delete all data (use only in development)
TRUNCATE TABLE news RESTART IDENTITY CASCADE;
TRUNCATE TABLE sync_log RESTART IDENTITY CASCADE;

-- Keep master data, only clear news
TRUNCATE TABLE news RESTART IDENTITY;
```

### Reset Database (Development Only)

```bash
# Drop and recreate schema
psql -h 127.0.0.1 -U govbrnews_app -d govbrnews <<EOF
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO govbrnews_app;
GRANT ALL ON SCHEMA public TO public;
EOF

# Recreate schema
./scripts/setup_database.sh
```

---

## Troubleshooting

### Connection Issues

**Problem**: Can't connect to database

```bash
# 1. Verify Cloud SQL status
gcloud sql instances describe destaquesgovbr-postgres

# 2. Check Cloud SQL Proxy is running
ps aux | grep cloud-sql-proxy

# 3. Kill stale proxy processes
lsof -ti:5432 | xargs kill -9

# 4. Restart proxy
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres
```

### Permission Errors

**Problem**: Permission denied

```bash
# Check service account permissions
gcloud projects get-iam-policy inspire-7-finep \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:YOUR_EMAIL"

# You should see:
# - roles/cloudsql.client
# - roles/secretmanager.secretAccessor
```

### Schema Creation Failed

**Problem**: Error during schema creation

```sql
-- Check what was created
SELECT tablename FROM pg_tables WHERE schemaname = 'public';
SELECT indexname FROM pg_indexes WHERE schemaname = 'public';
SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema = 'public';

-- Drop incomplete schema and retry
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
```

Then run `./scripts/setup_database.sh` again.

---

## CI/CD Integration

### GitHub Actions

The database can be accessed from GitHub Actions workflows:

```yaml
- name: Run database migrations
  run: |
    # Cloud SQL Proxy is auto-configured via Workload Identity
    cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &

    # Get password from Secret Manager
    PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

    # Run migration
    psql "host=127.0.0.1 dbname=govbrnews user=govbrnews_app password=$PASSWORD" \
      -f scripts/migrations/migration.sql
```

---

## Performance Monitoring

### Query Performance

```sql
-- Enable query stats extension (run once)
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- View slow queries
SELECT
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 1000  -- > 1 second
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Index Usage

```sql
-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

-- Find unused indexes
SELECT
    schemaname,
    tablename,
    indexname
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexname NOT LIKE '%_pkey'
ORDER BY tablename, indexname;
```

### Table Sizes

```sql
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

See also:
- [Database Schema](./schema.md)
- [Cloud SQL Documentation](../../infra/docs/cloud-sql.md)
- [Migration Plan](_plan/README.md)
