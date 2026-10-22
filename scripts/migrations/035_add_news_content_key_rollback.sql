-- Rollback for 035_add_news_content_key.sql
-- ARTICLE_CONTENT_KEY_SQL (jobs/graph/edges.py) e a graphql-api (GQL-1b) leem n.content_key:
-- reverter o codigo deles junto (ou antes) do rollback, senao o grafo e as queries quebram.

SET LOCAL lock_timeout = '10s';

ALTER TABLE news DROP COLUMN IF EXISTS content_key;
