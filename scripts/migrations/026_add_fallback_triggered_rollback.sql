-- Rollback for 026_add_fallback_triggered.sql

DROP INDEX IF EXISTS idx_scrape_runs_fallback;
ALTER TABLE scrape_runs DROP COLUMN IF EXISTS fallback_triggered;
