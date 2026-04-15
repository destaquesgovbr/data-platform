-- 005_alter_unique_id_varchar.sql
-- Widen unique_id to VARCHAR(120) for readable slug format
-- Add legacy_unique_id to preserve MD5 IDs for rollback and URL redirects
--
-- Ref: https://github.com/destaquesgovbr/data-platform/issues/43

BEGIN;

-- Step 1: Add legacy column to preserve old MD5 IDs
ALTER TABLE news ADD COLUMN IF NOT EXISTS legacy_unique_id VARCHAR(32);

-- Step 2: Backfill legacy column with current MD5 IDs
-- IMPORTANT: Must run BEFORE migration 006 (which converts unique_id to slugs)
-- Re-execution is safe: WHERE IS NULL filters out already-populated rows
UPDATE news SET legacy_unique_id = unique_id WHERE legacy_unique_id IS NULL;

-- Step 3: Widen unique_id on news table (only if still narrower than 120)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'news'
      AND column_name = 'unique_id'
      AND character_maximum_length < 120
  ) THEN
    ALTER TABLE news ALTER COLUMN unique_id TYPE VARCHAR(120);
  END IF;
END $$;

-- Step 4: Widen unique_id on news_features table (only if still narrower than 120)
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'news_features'
      AND column_name = 'unique_id'
      AND character_maximum_length < 120
  ) THEN
    ALTER TABLE news_features ALTER COLUMN unique_id TYPE VARCHAR(120);
  END IF;
END $$;

-- Step 5: Recreate the view (idempotent with OR REPLACE)
CREATE OR REPLACE VIEW news_with_themes AS
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

-- Step 6: Index on legacy_unique_id for redirect lookups
CREATE INDEX IF NOT EXISTS idx_news_legacy_unique_id ON news(legacy_unique_id);

-- Step 7: Update schema_version
INSERT INTO schema_version (version, description)
VALUES ('1.3', 'Widen unique_id to VARCHAR(120) for readable slugs, add legacy_unique_id')
ON CONFLICT (version) DO NOTHING;

COMMIT;
