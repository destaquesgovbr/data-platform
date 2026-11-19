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

## scrape_runs.articles_new (037)

`037_add_scrape_runs_articles_new.sql` adds `scrape_runs.articles_new INTEGER NULL` (rows truly
inserted in `news` by that scraper call; `articles_saved` keeps meaning inserted + updated) and
the partial index `idx_scrape_runs_success_articles_new`, the 008 stale-agency index over the new
column. Additive and metadata-only; the scraper in production names its INSERT columns, so it
keeps working, with `articles_new` NULL.

**Order:** apply 037 in production (`db-migrate`, `migrate --target 037` after `status`)
**before** deploying a scraper that writes `articles_new`. Without the column every
`scrape_runs` INSERT fails, the error is only logged, and the monitor loses every agency's runs.
Roll back in the reverse order: scraper first, then `rollback 037`.

Both directions take ACCESS EXCLUSIVE on `scrape_runs` and set `lock_timeout = '10s'` (as 032 and
035 do): behind a long transaction on the table they fail whole, with `lock timeout`, instead of
queueing every scraper INSERT behind them. Just run them again.

A reader that spans old and new rows with `COALESCE(articles_new, articles_saved) > 0` uses
neither partial index (the table is small, ~126k rows at most, so a scan is fine). Once the
90-day retention has replaced every pre-037 row, the query can filter `articles_new > 0` and use
the new index.

## scrape_agency_state (038)

`038_create_scrape_agency_state.sql` creates `scrape_agency_state`, one row per scraper
`agency_key` (gov.br and EBC) with the polling tier and interval, the next due time, the
watermark, the consecutive failures and the circuit breaker, and `scrape_dispatch_meta`, the
key-value store of the scraper-api `/dispatch`. The scraper-api writes the state in the same
transaction as its `scrape_runs` INSERT; `/dispatch`, `GET /agencies/state` and the infra-health
panel read it. No FK to `agencies` (`ansn` and `povosindigenas` are not there) and no
`updated_at` trigger (the scraper sets the column). Ref: `scraper/_plan/rearquitetura-ingestao.md`,
Step 2.

The seed inserts one row per `agency_key` with a `scrape_runs` row in the last 7 days (149 on
19/11/2026: the 147 active gov.br agencies plus `agencia_brasil` and `tvbrasil`) with
`ON CONFLICT DO NOTHING`, so re-running it only adds missing agencies and never overwrites state
the scraper already wrote:

| Column | Seed value |
|--------|------------|
| `last_attempt_at` | `max(scraped_at)` |
| `last_success_at` | latest successful `scraped_at` in the whole history (90-day retention): the real watermark, even for an agency failing for more than 7 days (the scraper caps the window at 7 days) |
| `last_error_category` / `last_error_message` | from the latest run if it failed (message cut at 500 chars), else NULL |
| `rate_ewma_per_day` | EWMA with a 7-day half-life (below); 0 without news in the window |
| `tier` / `poll_interval_minutes` | ≥ 5/day `m30`/30; ≥ 1 `h2`/120; ≥ 0.2 `h6`/360; else `d1`/1440 |
| `tier_updated_at`, `next_due_at` | `NOW()`: every agency is due on the first dispatch |
| counters, `circuit_state` | 0, `closed` |

The rate counts `news` per `agency_key` and BRT day of `published_at` over the 28 complete BRT
days before today (today, still partial, is left out), with 0 on days without news:
`rate = sum(n_d * w_d) / sum(w_d)`, `w_d = 0.5 ^ (age_d / 7)`, age 0 = yesterday. The daily tier
recomputation in `/dispatch` uses the same formula. Active agencies without a recent run get
their row from the scraper (`ensure_rows`); the seed cannot read the scraper's YAML.

**Cost:** `news` is read only on the 28-day `published_at` range through `idx_news_published_at`
(~6.6k rows; the bounds are stable expressions, usable as index keys) and grouped by
`agency_key`. `scrape_runs` goes through `idx_scrape_runs_scraped_agency` (keys of the last 7
days, index-only) and `idx_scrape_runs_agency_scraped` (latest run and latest success per
agency). With production-like volume (363k news, 1.9M runs) the seed took ~27 ms. A SQL
migration's dry-run reports no counts; for numbers, run the seed's query without the `INSERT` by hand.

**Locks:** both tables are new and the seed only reads `scrape_runs` and `news` (ACCESS SHARE,
compatible with the scraper's INSERTs), so applying 038 does not wait for the scraper.
`lock_timeout = '10s'` (as in 032, 035 and 037) only bites behind an ACCESS EXCLUSIVE holder of
those tables (another migration) and, on rollback, behind any open transaction on
`scrape_agency_state`: it then fails whole and is just re-run.

**Order:** apply 038 in production (`db-migrate`: `status`, then `migrate --target 038` with
`dry_run=true`, then `dry_run=false` + `confirm=true`) **before** deploying the scraper that
writes the state. That scraper writes the state inside a savepoint and keeps recording
`scrape_runs` without the table, but the circuit breaker, the watermark and `/agencies/state`
(503) need it. Roll back in the reverse order: scraper first, then `rollback 038`, which drops
both tables (the state is lost; re-applying 038 seeds again from `scrape_runs` and `news`).

038 is the target of `test_rollback_last_and_reapply`, so its seed must stay idempotent, and the
word `CONCURRENTLY` must not appear in it, not even in a comment: the integration tests would
treat it as a non-transactional migration and `stamp` it (with every pending one before it).

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
