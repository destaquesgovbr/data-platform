-- Rollback for 012_add_url_unique_index.sql

DROP INDEX IF EXISTS idx_news_agency_url_unique;

DELETE FROM schema_version WHERE version = '1.6';
