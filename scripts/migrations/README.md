# Database Migrations

Migrations for the destaquesgovbr data-platform PostgreSQL database.

## Usage

Use the generic migration runner:

```bash
# Show status of all migrations
python scripts/migrate.py status

# Apply pending migrations (dry-run)
python scripts/migrate.py migrate --dry-run

# Apply pending migrations
python scripts/migrate.py migrate --yes

# Rollback a specific migration
python scripts/migrate.py rollback 006 --yes

# Show history
python scripts/migrate.py history

# Validate consistency
python scripts/migrate.py validate
```

## Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| SQL migration | `NNN_description.sql` | `005_alter_unique_id_varchar.sql` |
| SQL rollback | `NNN_description_rollback.sql` | `005_alter_unique_id_varchar_rollback.sql` |
| Python migration | `NNN_description.py` | `006_migrate_unique_ids.py` |

## Current Migrations

| # | File | Type | Description |
|---|------|------|-------------|
| 001 | `001_add_pgvector_extension.sql` | SQL | Enable pgvector |
| 002 | `002_add_embedding_column.sql` | SQL | Add embedding columns |
| 003 | `003_create_embedding_index.sql` | SQL | HNSW indexes |
| 004 | `004_create_news_features.sql` | SQL | Feature store table |
| 005 | `005_alter_unique_id_varchar.sql` | SQL | Widen unique_id to VARCHAR(120) |
| 006 | `006_migrate_unique_ids.py` | Python | Migrate unique_ids to readable slugs |
| 007 | `007_create_idx_news_video_no_image.sql` | SQL | Partial index for thumbnail batch query |
| 008 | `008_create_scrape_runs.sql` | SQL | Scrape runs tracking table |
| 009 | `009_add_content_hash_and_url_index.sql` | SQL | Content hash + URL index for dedup |
| 010 | `010_backfill_content_hash.py` | Python | Backfill content_hash (SHA-256) |
| 011 | `011_cleanup_url_duplicates.py` | Python | Remove URL-based duplicates |
| 012 | `012_add_url_unique_index.sql` | SQL | Unique index on (agency_key, url) |

See [docs/database/migrations.md](../../docs/database/migrations.md) for full documentation.
