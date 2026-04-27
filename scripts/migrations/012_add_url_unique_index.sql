-- 012_add_url_unique_index.sql
-- Cria indice unico parcial em (agency_key, url) para prevenir duplicatas.
-- DEVE ser executado DEPOIS do cleanup de duplicatas (011).
-- Ref: destaquesgovbr/portal#108, destaquesgovbr/data-platform#138

CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_news_agency_url_unique
    ON news (agency_key, url)
    WHERE url IS NOT NULL;

INSERT INTO schema_version (version, description)
VALUES ('1.6', 'Add unique partial index on (agency_key, url)')
ON CONFLICT (version) DO NOTHING;
