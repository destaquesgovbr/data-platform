-- Rollback for 009_add_content_hash_and_url_index.sql

BEGIN;

DROP INDEX IF EXISTS idx_news_content_hash;

ALTER TABLE news DROP COLUMN IF EXISTS content_hash;

-- Restaurar FK original (sem ON UPDATE CASCADE)
ALTER TABLE news_features DROP CONSTRAINT IF EXISTS news_features_unique_id_fkey;
ALTER TABLE news_features ADD CONSTRAINT news_features_unique_id_fkey
    FOREIGN KEY (unique_id) REFERENCES news(unique_id) ON DELETE CASCADE;

-- Recriar view (sem content_hash a coluna ja nao existe)
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

DELETE FROM schema_version WHERE version = '1.5';

COMMIT;
