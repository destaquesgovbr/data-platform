-- 009_add_content_hash_and_url_index.sql
-- Adiciona coluna content_hash para deduplicacao cross-agency e
-- atualiza FK de news_features com ON UPDATE CASCADE.
-- Ref: destaquesgovbr/portal#108, destaquesgovbr/data-platform#138

BEGIN;

-- Coluna content_hash (SHA-256 truncado 16 hex)
ALTER TABLE news ADD COLUMN IF NOT EXISTS content_hash VARCHAR(16);

-- Medida defensiva: adicionar ON UPDATE CASCADE a FK de news_features
ALTER TABLE news_features DROP CONSTRAINT IF EXISTS news_features_unique_id_fkey;
ALTER TABLE news_features ADD CONSTRAINT news_features_unique_id_fkey
    FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE ON UPDATE CASCADE;

-- Indice para agrupamento por content_hash (nao-unique)
CREATE INDEX IF NOT EXISTS idx_news_content_hash ON news(content_hash) WHERE content_hash IS NOT NULL;

-- View news_with_themes depende de news.* e precisa ser recriada
DROP VIEW IF EXISTS news_with_themes;
CREATE VIEW news_with_themes AS
SELECT
    n.id, n.unique_id, n.title, n.url, n.agency_name, n.published_at, n.summary,
    t1.label as theme_l1, t2.label as theme_l2, t3.label as theme_l3,
    COALESCE(t3.label, t2.label, t1.label) as most_specific_theme
FROM news n
LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
LEFT JOIN themes t3 ON n.theme_l3_id = t3.id;

INSERT INTO schema_version (version, description)
VALUES ('1.5', 'Add content_hash column, update news_features FK with ON UPDATE CASCADE')
ON CONFLICT (version) DO NOTHING;

COMMIT;
