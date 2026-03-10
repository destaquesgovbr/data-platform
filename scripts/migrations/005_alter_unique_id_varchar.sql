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

-- Step 3: Widen unique_id on news table
ALTER TABLE news ALTER COLUMN unique_id TYPE VARCHAR(120);

-- Step 4: Widen unique_id on news_features table
ALTER TABLE news_features ALTER COLUMN unique_id TYPE VARCHAR(120);

-- Step 5: Index on legacy_unique_id for redirect lookups
CREATE INDEX IF NOT EXISTS idx_news_legacy_unique_id ON news(legacy_unique_id);

-- Step 6: Update schema_version
INSERT INTO schema_version (version, description)
VALUES ('1.3', 'Widen unique_id to VARCHAR(120) for readable slugs, add legacy_unique_id')
ON CONFLICT (version) DO NOTHING;

COMMIT;
