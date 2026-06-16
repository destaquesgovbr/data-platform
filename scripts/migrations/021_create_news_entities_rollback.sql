-- 021_create_news_entities_rollback.sql
-- Rollback: remove a tabela news_entities (os indices idx_news_entities_* vao junto).

DROP TABLE IF EXISTS news_entities;
