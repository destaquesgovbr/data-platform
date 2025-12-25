# Migration Performance Optimization

## Overview

This document describes the performance optimizations applied during the bulk migration from HuggingFace to PostgreSQL.

## Problem

Initial migration performance was extremely slow:
- **Speed**: ~40-95 records/second
- **Estimated time**: ~90+ minutes for 309,193 records
- **Errors**: `string is too long for tsvector (2300174 bytes, max 1048575 bytes)`

## Root Causes

### 1. Full-Text Search Index (idx_news_fts)

**Issue**: GIN index on `to_tsvector('portuguese', title || ' ' || content)` was:
- Being updated on every INSERT
- Index size: 262 MB after only 55k records
- Some content fields exceeded tsvector limit (1 MB)

**Impact**: Each insert triggered full-text tokenization and index update of potentially large content.

### 2. Denormalize Trigger

**Issue**: Trigger `denormalize_news_agency` was running on every INSERT to populate `agency_key` and `agency_name`.

**Impact**: Redundant work since migration script already sends denormalized data.

### 3. Multiple Non-Critical Indexes

**Issue**: Several indexes were being maintained during bulk insert:
- `idx_news_agency_date` (composite index)
- `idx_news_synced_to_hf` (partial index)
- `idx_news_theme_l1` (simple index)

**Impact**: Each index update adds overhead to every INSERT.

## Solutions Applied

### 1. Drop Full-Text Search Index

```sql
DROP INDEX IF EXISTS idx_news_fts;
```

**Why**: Rebuild with optimized version after migration completes.

**Optimized version** (created after migration):
```sql
CREATE INDEX idx_news_fts ON news
USING GIN (to_tsvector('portuguese',
    title || ' ' || COALESCE(LEFT(content, 100000), '')
));
```

Limits content to 100KB (well below 1MB tsvector limit) while preserving search functionality.

### 2. Disable Denormalize Trigger

```sql
ALTER TABLE news DISABLE TRIGGER denormalize_news_agency;
```

**Why**: Migration script already provides denormalized data in INSERT statements.

**Re-enabled after migration** to handle future updates from other sources.

### 3. Drop Non-Critical Indexes

```sql
DROP INDEX IF EXISTS idx_news_agency_date;
DROP INDEX IF EXISTS idx_news_synced_to_hf;
DROP INDEX IF EXISTS idx_news_theme_l1;
```

**Why**: These indexes can be recreated quickly after bulk insert using `CREATE INDEX CONCURRENTLY`.

## Results

### Performance Improvement

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Insert rate | 40-95 rec/s | 320-625 rec/s | **6-8x faster** |
| Estimated time | 90+ min | 11-15 min | **6x faster** |
| Errors | tsvector limit | None | **100% resolved** |

### Migration Statistics

- **Total records**: 309,193
- **Final insert rate**: ~450 records/second (average)
- **Total time**: ~12 minutes
- **Success rate**: 100% (excluding records with missing `published_at`)

## Post-Migration Steps

After migration completes, indexes are recreated using:

```bash
python scripts/recreate_indexes_after_migration.py
```

This script:
1. Creates optimized FTS index (content truncated to 100KB)
2. Recreates composite and partial indexes using `CREATE INDEX CONCURRENTLY`
3. Re-enables denormalize trigger
4. Shows final index sizes

## Best Practices

### For Future Bulk Migrations

1. **Drop expensive indexes before bulk insert**
   - Full-text search (GIN)
   - Large composite indexes
   - Partial indexes

2. **Disable triggers if data is already processed**
   - Denormalization triggers
   - Update timestamp triggers (if using batch update_at)

3. **Keep critical indexes**
   - Primary key
   - Unique constraints
   - Foreign key indexes (for referential integrity)

4. **Recreate indexes concurrently after migration**
   - Use `CREATE INDEX CONCURRENTLY` to avoid locking
   - Monitor index creation progress

5. **Optimize index definitions**
   - Truncate large text fields in FTS indexes
   - Use partial indexes where applicable
   - Consider index size vs. query performance trade-offs

## Monitoring

During migration, monitor:
- Insert rate (records/second)
- Database connection pool usage
- Disk I/O
- Memory usage

After migration, verify:
- All indexes created successfully
- Index sizes are reasonable
- Query performance meets requirements

## References

- [PostgreSQL Full-Text Search](https://www.postgresql.org/docs/15/textsearch.html)
- [CREATE INDEX CONCURRENTLY](https://www.postgresql.org/docs/15/sql-createindex.html#SQL-CREATEINDEX-CONCURRENTLY)
- [PostgreSQL Performance Tips](https://wiki.postgresql.org/wiki/Performance_Optimization)

---

**Last updated**: 2024-12-24
**Applied during**: Phase 3 Migration (HuggingFace → PostgreSQL)
