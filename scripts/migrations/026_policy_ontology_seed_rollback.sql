-- 026_policy_ontology_seed_rollback.sql
-- Remove campos de ontologia adicionados pela migração 026
-- AVISO: Remove entidades que foram inseridas pelo gazetteer (provenance = 'gazetteer')

-- 1. Remover entidades inseridas diretamente pelo gazetteer
DELETE FROM entity_registry
WHERE provenance = 'gazetteer'
  AND type = 'POLICY';

-- 2. Limpar campos de ontologia de entidades pré-existentes que foram atualizadas
UPDATE entity_registry
SET extra = extra - 'domain' - 'lifecycle_phase' - 'instance_of' - 'wikidata_id'
WHERE type = 'POLICY'
  AND extra ? 'domain';
