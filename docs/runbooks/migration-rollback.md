# Runbook: Migration Rollback

Procedures for rolling back database migrations in the destaquesgovbr data-platform.

---

## Prerequisites

- Access to `DATABASE_URL` (via Secret Manager or `.env.local`)
- Cloud SQL Proxy running (for production) or Docker PostgreSQL (for local)
- Python environment with dependencies installed (`poetry install`)

---

## Scenario A: Rollback a Python Migration (e.g., 006)

Python migrations that modify data (not schema) are the simplest to rollback.

```bash
# 1. Preview the rollback
python scripts/migrate.py rollback 006 --dry-run

# 2. Execute the rollback
python scripts/migrate.py rollback 006 --yes

# 3. Verify
python scripts/migrate.py status
python scripts/migrate.py history
```

**Via CI/CD:**
1. Go to Actions > Database Migration
2. Set: command=`rollback`, target_version=`006`, dry_run=`true`
3. Review the output
4. Re-run with dry_run=`false`, confirm=`true`

---

## Scenario B: Rollback a SQL Migration with Rollback File

SQL migrations with a corresponding `_rollback.sql` file.

```bash
# 1. Preview
python scripts/migrate.py rollback 005 --dry-run

# 2. Execute
python scripts/migrate.py rollback 005 --yes

# 3. Verify
python scripts/migrate.py status
```

**Important:** Rollback 005 (unique_id VARCHAR) requires that 006 (data migration) is rolled back first. Always rollback in reverse order.

---

## Scenario C: Rollback a SQL Migration WITHOUT Rollback File

If no `_rollback.sql` exists, the runner will error. You must:

1. Write the rollback SQL manually
2. Save as `NNN_description_rollback.sql` in `scripts/migrations/`
3. Run `python scripts/migrate.py rollback NNN --yes`

Or execute the rollback SQL directly:

```bash
psql "$DATABASE_URL" -f path/to/manual_rollback.sql
```

Then record it in history:

```sql
INSERT INTO migration_history (version, name, migration_type, operation, status, applied_by, description)
VALUES ('NNN', 'description', 'sql', 'rollback', 'success', 'manual', 'Manual rollback');
```

---

## Scenario D: Full Rollback to a Previous State

To rollback multiple migrations in reverse order:

```bash
# Rollback 006, then 005, then 004 (reverse order)
python scripts/migrate.py rollback 006 --yes
python scripts/migrate.py rollback 005 --yes
python scripts/migrate.py rollback 004 --yes

# Verify final state
python scripts/migrate.py status
```

---

## Scenario E: CONCURRENTLY Failure (INVALID Index)

When a `CREATE INDEX CONCURRENTLY` fails (timeout, deadlock, crash), PostgreSQL leaves the index in an INVALID state. INVALID indexes are not used by the query planner but consume space and block retries.

### Diagnosis

```bash
# Check for INVALID indexes
psql "$DATABASE_URL" -c "
SELECT indexrelid::regclass AS index_name,
       indrelid::regclass AS table_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_index
WHERE NOT indisvalid;
"
```

### Recovery Steps

```bash
# 1. Drop the INVALID index
psql "$DATABASE_URL" -c "DROP INDEX CONCURRENTLY IF EXISTS idx_news_agency_url_unique;"

# 2. Verify migration_history shows the failed attempt
python scripts/migrate.py history --limit 5

# 3. Re-run the migration (runner will detect it as pending due to pre-recorded failed status)
python scripts/migrate.py migrate --yes

# 4. Verify success
python scripts/migrate.py status
```

### Via CI/CD

1. Drop the INVALID index manually via Cloud SQL Console or Cloud Shell
2. Go to Actions > Database Migration
3. Set: command=`migrate`, dry_run=`false`, confirm=`true`

### Important Notes

- `DROP INDEX CONCURRENTLY` also cannot run inside a transaction — execute it directly via `psql`
- The pre-recorded `failed` entry in `migration_history` means the runner still sees the migration as "not successfully applied" and will retry
- If the migration has multiple statements and one succeeded before the failure, the idempotent patterns (`IF NOT EXISTS`) ensure safe re-execution
- Monitor for lock contention on large tables when retrying CONCURRENTLY indexes

---

## Emergency: Restore from Backup

If rollback is not possible or data corruption occurred:

```bash
# 1. List available backups
gcloud sql backups list --instance=destaquesgovbr-postgres --limit=5

# 2. Restore from a specific backup
gcloud sql backups restore BACKUP_ID --restore-instance=destaquesgovbr-postgres

# 3. Verify the restoration
python scripts/migrate.py status
```

**Warning:** Backup restore replaces ALL data in the instance. All databases (govbrnews, umami, keycloak, federation) will be affected.

---

## Post-Rollback Checklist

- [ ] Verify `python scripts/migrate.py status` shows expected state
- [ ] Check `migration_history` for rollback record
- [ ] Test application connectivity (DAGs, portal, scraper)
- [ ] If unique_ids changed: trigger Typesense full-sync
- [ ] If unique_ids changed: verify HuggingFace sync
- [ ] Notify team in appropriate channel

---

See also:
- [Migration System Documentation](../database/migrations.md)
- [Composer Recovery Runbook](./composer-recovery.md)
