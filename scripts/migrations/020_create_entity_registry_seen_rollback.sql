-- Rollback de 020_create_entity_registry_seen.sql
DROP TRIGGER IF EXISTS trg_entity_registry_seen_updated_at ON entity_registry_seen;
DROP FUNCTION IF EXISTS update_entity_registry_seen_updated_at();
DROP TABLE IF EXISTS entity_registry_seen;
