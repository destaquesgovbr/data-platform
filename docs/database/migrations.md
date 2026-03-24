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

---

See also:
- [Database Schema](./schema.md)
- [Migration Rollback Runbook](../runbooks/migration-rollback.md)
