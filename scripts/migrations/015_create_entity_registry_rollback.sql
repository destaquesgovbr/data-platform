-- 015_create_entity_registry_rollback.sql
-- Rollback: remove entity_registry e objetos relacionados.
-- NOTA: NAO removemos a extensao pg_trgm aqui — outras tabelas/indices podem depender dela.
--       Deixe-a instalada de proposito.

DROP TRIGGER IF EXISTS trg_entity_registry_updated_at ON entity_registry;
DROP FUNCTION IF EXISTS update_entity_registry_updated_at();
-- Os indices (idx_entity_registry_*) sao removidos automaticamente com o DROP TABLE.
DROP TABLE IF EXISTS entity_registry;
