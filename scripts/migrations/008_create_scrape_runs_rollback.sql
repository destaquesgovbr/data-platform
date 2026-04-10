-- Rollback for 008_create_scrape_runs.sql

DROP INDEX IF EXISTS idx_scrape_runs_success_articles;
DROP INDEX IF EXISTS idx_scrape_runs_scraped_agency;
DROP INDEX IF EXISTS idx_scrape_runs_status;
DROP INDEX IF EXISTS idx_scrape_runs_agency_scraped;
DROP TABLE IF EXISTS scrape_runs;
