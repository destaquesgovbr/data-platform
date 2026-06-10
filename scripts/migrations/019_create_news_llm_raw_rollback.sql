-- 019_create_news_llm_raw_rollback.sql
-- Rollback: remove a tabela news_llm_raw (os indices idx_news_llm_raw_* vao junto).

DROP TABLE IF EXISTS news_llm_raw;
