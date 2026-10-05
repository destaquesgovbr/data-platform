-- Rollback for 029_entity_trending_baseline.sql

ALTER TABLE entity_trending_scores
    DROP COLUMN IF EXISTS baseline_count,
    DROP COLUMN IF EXISTS baseline_agencies;
