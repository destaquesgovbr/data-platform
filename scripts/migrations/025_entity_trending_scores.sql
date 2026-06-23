-- 025_entity_trending_scores.sql
-- Tabela de entidades NER com maior crescimento de cobertura.
-- Populada pelo DAG compute_entity_trending (4× ao dia).
-- UPSERT idempotente: PRIMARY KEY (entity_id) garante atomicidade.

CREATE TABLE IF NOT EXISTS entity_trending_scores (
    entity_id          TEXT        NOT NULL,
    canonical_name     TEXT        NOT NULL,
    type               TEXT        NOT NULL,
    trending_score     FLOAT       NOT NULL,
    volume_ratio       FLOAT       NOT NULL,
    window_count       INTEGER     NOT NULL,
    window_agencies    INTEGER     NOT NULL,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_trending_score
    ON entity_trending_scores (trending_score DESC);
