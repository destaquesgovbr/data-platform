-- 029_entity_trending_baseline.sql
-- Persiste o baseline usado no volume_ratio de entity_trending_scores (Fase 2.5, F2).
-- Colunas nulas: linhas gravadas antes desta migração ficam com NULL; o DAG
-- compute_entity_trending passa a preenchê-las a cada execução.
-- Sem índice: o persist apaga as execuções anteriores (DELETE computed_at < NOW()),
-- então a tabela guarda só o snapshot corrente (centenas de linhas).

ALTER TABLE entity_trending_scores
    ADD COLUMN IF NOT EXISTS baseline_count INTEGER,
    ADD COLUMN IF NOT EXISTS baseline_agencies INTEGER;
