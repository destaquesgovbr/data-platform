-- Rollback for 032_entity_stats.sql
-- A DAG project_entity_graph da versao com DP-1 falha sem estas tabelas/coluna: reverter o
-- codigo do job junto (ou antes) do rollback.

SET LOCAL lock_timeout = '10s';

DROP TABLE IF EXISTS entity_graph_meta;
DROP TABLE IF EXISTS entity_stats;
ALTER TABLE entity_edges DROP COLUMN IF EXISTS unique_content_count;
