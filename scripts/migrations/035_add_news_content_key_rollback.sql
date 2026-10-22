-- Rollback for 035_add_news_content_key.sql
-- O grafo (jobs/graph/edges.py) e a task compute_content_keys detectam a coluna ausente e caem
-- no content_hash (com aviso). A graphql-api (GQL-1b, _CONTENT_DEDUP_KEY_SQL) le n.content_key
-- direto: reverter o codigo dela antes do rollback, senao as queries quebram.

SET LOCAL lock_timeout = '10s';

ALTER TABLE news DROP COLUMN IF EXISTS content_key;
