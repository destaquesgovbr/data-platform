-- Rollback for 037_add_scrape_runs_articles_new.sql
-- Fazer o rollback do scraper que grava articles_new ANTES: sem a coluna o INSERT dele falha.

-- Mesmo lock_timeout da 037: o DROP INDEX e o DROP COLUMN pedem ACCESS EXCLUSIVE.
SET LOCAL lock_timeout = '10s';

DROP INDEX IF EXISTS idx_scrape_runs_success_articles_new;
ALTER TABLE scrape_runs DROP COLUMN IF EXISTS articles_new;
