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

## Reserved Versions

`RESERVED_VERSIONS` in `scripts/migrate.py` lists numbers held for PRs still open; `validate`
does not report them as gaps. Remove the entry when the PR lands with its file.

| # | Held for |
|---|----------|
| 030 | data-platform#189 (summary moderation) |
| 031 | data-platform#184 (BGE-M3) |
| 034 | tema 26 Defesa Civil (DP-2, `feature/tema-26-migracao`) |

## Backfills

Python backfills run with the pending SQL migrations unless targeted. To apply only a schema
migration and leave a later backfill for its own window, use `--target`, e.g.
`migrate --target 032` (leaves `033_backfill_readability_flesch_ptbr.py` pending), and
dry-run the backfill first: its preview reports the pending count and a projected run time.

`--target NNN` applies **every** pending migration up to and including NNN, not just NNN. Run
`status` first: if an earlier backfill is still pending (e.g. 033 when targeting 035), it runs
in the same call, outside its own window. Apply the earlier ones first, in their windows.

Likewise `migrate --target 035` adds `news.content_key` and leaves
`036_backfill_news_content_key.py` (near-duplicate key for the whole corpus, 90-day chunks,
idempotent) for its own window — with 033 and 034 already applied, otherwise they run too; its dry-run computes the last 30 days without writing and
projects time and changes. A `migrate --dry-run` with 035 and 036 both pending only reports that
035 must be applied first (the runner rolls back the 035 preview before 036 runs).

## Theme changes (034)

`034_tema26_defesa_civil.py` creates theme 26 (Defesa Civil e Gestão de Desastres), remaps
`news` from 19.03*/19.04* to 26.01*/26.02* in one transaction and deletes the old codes. Every
change goes to the `news_theme_changes` audit table, exactly as in the 22/10 contract: `id`,
`campaign`, `unique_id`, the 4 old and 4 new theme codes (codes, not ids), `source`, `note`,
`changed_at`, `reverted_at`, plus `UNIQUE (campaign, unique_id)` (one row per article and
campaign). There are two campaigns: the migration writes `tema26-034` (source `migration-034`,
`note` = the remap rule) and the LLM reclassification (data-science#49) writes `tema26-llm-d1`
(source `llm:<model_id>`). Its dry-run applies everything inside a savepoint and rolls it
back, logging the counts per code and per rule. Its rollback reads only those two campaigns,
from the most recent `changed_at` to the oldest (on a tie, the LLM row first), restores each
article to its state before the first change and only sets `reverted_at` on the rows it read
(no new audit rows); articles in theme 26 without audit rows are undone by the inverse map and
listed as `unaudited_inverse_map` in the log. Apply it with `migrate --target 034` after
`status`: pending means "not in the history", so with 035/036 already applied only 034 runs.
Never use `scripts/populate_themes.py` in production (it deletes `themes` and reinserts with
new ids).

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
