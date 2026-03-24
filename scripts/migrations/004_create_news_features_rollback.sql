-- 004_create_news_features_rollback.sql
-- Rollback: remove news_features table and related objects

DROP TRIGGER IF EXISTS trg_news_features_updated_at ON news_features;
DROP FUNCTION IF EXISTS update_news_features_updated_at();
DROP INDEX IF EXISTS idx_news_features_gin;
DROP INDEX IF EXISTS idx_news_features_updated_at;
DROP TABLE IF EXISTS news_features;
