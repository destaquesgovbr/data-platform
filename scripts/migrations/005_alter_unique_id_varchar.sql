-- 005_alter_unique_id_varchar.sql
-- Widen unique_id to VARCHAR(120) for readable slug format
-- Add legacy_unique_id to preserve MD5 IDs for rollback and URL redirects
--
-- Ref: https://github.com/destaquesgovbr/data-platform/issues/43

BEGIN;

-- Step 1: Add legacy column to preserve old MD5 IDs
ALTER TABLE news ADD COLUMN IF NOT EXISTS legacy_unique_id VARCHAR(32);

-- Step 2: Backfill legacy column with current MD5 IDs
UPDATE news SET legacy_unique_id = unique_id WHERE legacy_unique_id IS NULL;

-- Step 3: Drop view that depends on news.unique_id (will be recreated in step 6)
DROP VIEW IF EXISTS news_with_themes;

-- Step 4: Widen unique_id on news table
ALTER TABLE news ALTER COLUMN unique_id TYPE VARCHAR(120);

-- Step 5: Widen unique_id on news_features table
ALTER TABLE news_features ALTER COLUMN unique_id TYPE VARCHAR(120);

-- Step 6: Recreate the view
CREATE VIEW news_with_themes AS
SELECT
    n.id,
    n.unique_id,
    n.title,
    n.url,
    n.agency_name,
    n.published_at,
    n.summary,
    t1.label as theme_l1,
    t2.label as theme_l2,
    t3.label as theme_l3,
    COALESCE(t3.label, t2.label, t1.label) as most_specific_theme
FROM news n
LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
LEFT JOIN themes t3 ON n.theme_l3_id = t3.id;

-- Step 7: Index on legacy_unique_id for redirect lookups
CREATE INDEX IF NOT EXISTS idx_news_legacy_unique_id ON news(legacy_unique_id);

-- Step 8: Update schema_version
INSERT INTO schema_version (version, description)
VALUES ('1.3', 'Widen unique_id to VARCHAR(120) for readable slugs, add legacy_unique_id')
ON CONFLICT (version) DO NOTHING;

COMMIT;
