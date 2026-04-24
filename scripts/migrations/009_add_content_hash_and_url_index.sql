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

INSERT INTO schema_version (version, description)
VALUES ('1.5', 'Add content_hash column, update news_features FK with ON UPDATE CASCADE')
ON CONFLICT (version) DO NOTHING;

COMMIT;
