-- 016_create_entity_alias_rollback.sql
-- Rollback: remove a tabela entity_alias (o indice idx_entity_alias_entity_id vai junto).

DROP TABLE IF EXISTS entity_alias;
