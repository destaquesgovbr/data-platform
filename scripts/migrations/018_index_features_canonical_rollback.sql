-- 018_index_features_canonical_rollback.sql
-- Rollback: remove o indice GIN de canonical_id em features->'entities'.

DROP INDEX IF EXISTS idx_features_entities_canonical;
