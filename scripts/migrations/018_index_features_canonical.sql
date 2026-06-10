-- 018_index_features_canonical.sql
-- Indice GIN (jsonb_path_ops) sobre features->'entities' para a consulta
-- "artigos que mencionam uma entidade canonica":
--   SELECT * FROM news_features WHERE features->'entities' @> '[{"canonical_id":"Q216330"}]'
-- Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.

CREATE INDEX IF NOT EXISTS idx_features_entities_canonical
    ON news_features USING GIN ((features -> 'entities') jsonb_path_ops);
