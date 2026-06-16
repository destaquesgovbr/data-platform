-- 022_create_entity_edges_rollback.sql
-- Rollback: remove a tabela entity_edges (os indices idx_entity_edges_* vao junto).

DROP TABLE IF EXISTS entity_edges;
