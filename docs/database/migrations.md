# Database Migrations

Generic migration system for the destaquesgovbr data-platform. Supports SQL and Python migrations with audit history, dry-run, and rollback.

---

## Quick Reference

```bash
# Show migration status
python scripts/migrate.py status

# Preview pending migrations (no changes)
python scripts/migrate.py migrate --dry-run

# Apply pending migrations
python scripts/migrate.py migrate --yes

# Apply up to a specific version
python scripts/migrate.py migrate --target 005 --yes

# Rollback a specific migration (preview)
python scripts/migrate.py rollback 006 --dry-run

# Rollback a specific migration
python scripts/migrate.py rollback 006 --yes

# Show migration history
python scripts/migrate.py history

# Validate migration files
python scripts/migrate.py validate
```

All commands require `DATABASE_URL` environment variable or `--db-url` flag.

---

## How It Works

### Runner: `scripts/migrate.py`

Single entry point for all migration operations. On first run, it bootstraps the `migration_history` table and imports existing entries from `schema_version`.

### Discovery

The runner discovers migration files in `scripts/migrations/` using naming conventions:

| Type | Pattern | Example |
|------|---------|---------|
| SQL migration | `NNN_description.sql` | `005_alter_unique_id_varchar.sql` |
| SQL rollback | `NNN_description_rollback.sql` | `005_alter_unique_id_varchar_rollback.sql` |
| Python migration | `NNN_description.py` | `006_migrate_unique_ids.py` |

Rollback files are automatically associated with their migration by version number.

### Execution

1. Discovers pending migrations (not yet in `migration_status` view)
2. Executes each in version order
3. Records result in `migration_history` within the same transaction (atomic commit)
4. On failure: rolls back transaction, records `status=failed` separately, stops immediately

### Python Migration Interface

Each `.py` migration file must expose:

```python
def describe() -> str:
    """Human description for logs and audit."""

def migrate(conn, dry_run: bool = False) -> dict:
    """Execute the migration. Returns metrics dict."""

def rollback(conn, dry_run: bool = False) -> dict:
    """Revert the migration. Raises NotImplementedError if not possible."""
```

The runner manages the connection and transaction. The migration must not call `conn.commit()` or `conn.rollback()`.

### Autocommit Migrations (CONCURRENTLY)

Migrations that use `CREATE INDEX CONCURRENTLY` or other DDL that cannot run inside a transaction must opt into autocommit mode.

#### Marking a Migration as Autocommit

Add `-- migrate: autocommit` as the **first line** of the `.sql` file:

```sql
-- migrate: autocommit
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_news_agency_url_unique
    ON news (agency_key, url)
    WHERE url IS NOT NULL;
```

#### How the Runner Handles Autocommit

1. **Detection**: checks first line for `-- migrate: autocommit`
2. **Pre-records history** as `status=failed` (audit trail in case of crash)
3. **Sets `autocommit=True`** on the connection
4. **Splits SQL by `;`** and executes each statement individually
5. On success: updates history to `status=success`
6. On failure: updates history to `status=failed` with error message, re-raises

#### Limitations

| Aspect | Behavior |
|--------|----------|
| Dry-run | **Skipped** — logged as "cannot be previewed" |
| Rollback | Not automatic — must be handled manually |
| SQL splitting | Simple `;` split — no support for `$$` blocks or string literals containing `;` |
| Suitable DDL | `CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `VACUUM`, `CREATE DATABASE` |

#### Failure Modes

- **Process crash during execution**: pre-recorded `failed` entry remains in history; index may be in INVALID state
- **Statement failure**: history updated to `failed` with error; partial state may persist (e.g., INVALID index)
- **Recovery**: see [Migration Rollback Runbook — Scenario E](../runbooks/migration-rollback.md#scenario-e-concurrently-failure-invalid-index)

---

## Migration History

### Table: `migration_history`

| Column | Type | Description |
|--------|------|-------------|
| version | VARCHAR(10) | Migration version (e.g. "005") |
| name | VARCHAR(255) | Migration name |
| migration_type | VARCHAR(10) | `sql` or `python` |
| operation | VARCHAR(10) | `migrate`, `rollback`, or `dry_run` |
| status | VARCHAR(20) | `success`, `failed`, or `unavailable` |
| applied_by | TEXT | `$GITHUB_ACTOR` or `$USER` |
| run_id | TEXT | `$GITHUB_RUN_ID` (CI/CD only) |
| duration_ms | INTEGER | Execution time in milliseconds |
| execution_details | JSONB | Metrics returned by Python migrations |
| error_message | TEXT | Error details on failure |

### View: `migration_status`

Shows the current state of each migration (latest successful operation per version).

```sql
SELECT * FROM migration_status ORDER BY version;
```

---

## CI/CD: GitHub Actions Workflow

The `db-migrate.yaml` workflow runs migrations via GitHub Actions with:

- Automatic backup before destructive operations
- Cloud SQL Proxy for secure database access
- Confirmation required for non-dry-run operations
- Post-execution status report

### Workflow Inputs

| Input | Type | Description |
|-------|------|-------------|
| command | choice | `status`, `migrate`, `rollback`, `history`, `validate` |
| dry_run | boolean | Preview without applying (default: true) |
| target_version | string | Version for `--target` or rollback |
| confirm | boolean | Required for destructive operations with dry_run=false |

---

## Creating a New Migration

### SQL Migration

1. Create `scripts/migrations/NNN_description.sql`
2. Optionally create `scripts/migrations/NNN_description_rollback.sql`
3. Test locally with `--dry-run`
4. Run via workflow or CLI

### Python Migration

1. Create `scripts/migrations/NNN_description.py`
2. Implement `describe()`, `migrate()`, `rollback()`
3. Add unit tests in `tests/unit/`
4. Test locally with `--dry-run`

---

## Current Migrations

| Version | File | Type | Description |
|---------|------|------|-------------|
| 001 | `001_add_pgvector_extension.sql` | SQL | Enable pgvector for vector search |
| 002 | `002_add_embedding_column.sql` | SQL | Add 768-dim embedding columns |
| 003 | `003_create_embedding_index.sql` | SQL | HNSW indexes for fast similarity |
| 004 | `004_create_news_features.sql` | SQL | JSONB feature store table |
| 005 | `005_alter_unique_id_varchar.sql` | SQL | Widen unique_id to VARCHAR(120) |
| 006 | `006_migrate_unique_ids.py` | Python | Migrate ~300k unique_ids to readable slugs |
| 007 | `007_create_idx_news_video_no_image.sql` | SQL | Partial index for thumbnail batch query optimization |
| 008 | `008_create_scrape_runs.sql` | SQL | Scrape runs tracking table (per-agency execution results) |
| 009 | `009_add_content_hash_and_url_index.sql` | SQL | Content hash column + URL index for deduplication |
| 010 | `010_backfill_content_hash.py` | Python | Backfill SHA-256 content_hash for existing rows |
| 011 | `011_cleanup_url_duplicates.py` | Python | Remove URL-based duplicates (keep records with embeddings) |
| 012 | `012_add_url_unique_index.sql` | SQL | Unique partial index on (agency_key, url) |

---

## Stamp Command

The `stamp` command marks migrations as applied **without executing them**. Use it when migrations were already applied outside of the runner.

### When to Use

| Scenario | Example |
|----------|---------|
| Existing DB before the runner was introduced | Migrations 001-007 were applied by a previous workflow that didn't record history |
| Restored from backup | Backup has schema changes but `migration_history` was truncated or absent |
| Staging from production snapshot | Clone production DB for testing — schema is current, history may differ |

### Usage

```bash
# Via CLI (local)
python scripts/migrate.py stamp 007 --yes --db-url "$DATABASE_URL"

# Via GitHub Actions workflow
# Inputs: command=stamp, target_version=007, confirm=true
```

### How It Differs from Migrate

| | `migrate` | `stamp` |
|-|-----------|---------|
| Executes SQL/Python | Yes | No |
| Records in `migration_history` | Yes (operation=migrate) | Yes (operation=migrate, description=stamped) |
| Requires confirmation | Yes (dry_run=false) | Always |
| Use case | Normal deployment | Bootstrap existing databases |

### Important

- `stamp` bypasses all safety checks — incorrect use can cause schema drift
- Always run `status` first to verify which migrations will be stamped
- After stamping, run `validate` to confirm consistency

---

## Idempotency Convention

All SQL migrations MUST be safe to re-execute. This prevents cascading failures when `migration_history` gets out of sync with actual schema state.

### Patterns

| Operation | Idempotent Pattern |
|-----------|--------------------|
| Create table | `CREATE TABLE IF NOT EXISTS` |
| Create index | `CREATE INDEX IF NOT EXISTS` |
| Add column | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| Create/replace function | `CREATE OR REPLACE FUNCTION` |
| Create/replace view | `CREATE OR REPLACE VIEW` |
| Create/replace trigger | `CREATE OR REPLACE TRIGGER` |
| Alter column type | `DO $$ BEGIN IF EXISTS (SELECT ... WHERE character_maximum_length < N) THEN ALTER ... END IF; END $$` |
| Insert reference data | `INSERT ... ON CONFLICT DO NOTHING` |
| Update data | Use WHERE clauses that make repeated execution a no-op |

### PostgreSQL Limitations

`ALTER COLUMN TYPE` has no `IF NOT EXISTS` equivalent. Use a conditional block:

```sql
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'news' AND column_name = 'unique_id'
      AND character_maximum_length < 120
  ) THEN
    ALTER TABLE news ALTER COLUMN unique_id TYPE VARCHAR(120);
  END IF;
END $$;
```

### Code Review Checklist

When reviewing a PR that adds or modifies migrations:

1. Every DDL statement uses `IF NOT EXISTS` / `CREATE OR REPLACE`
2. Data mutations (UPDATE/INSERT) have WHERE clauses that make them no-ops on re-run
3. If the migration ran twice by accident, would it produce the same end state?

---

See also:
- [Database Schema](./schema.md)
- [Migration Rollback Runbook](../runbooks/migration-rollback.md)
