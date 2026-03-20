-- 005_alter_unique_id_varchar_rollback.sql
-- Rollback: revert unique_id to VARCHAR(32) and remove legacy_unique_id
--
-- WARNING: This rollback will FAIL if any unique_id exceeds 32 chars.
-- Run 006 rollback first to restore MD5 IDs before running this.
--
-- NOTE: Do NOT use BEGIN/COMMIT here. The migration runner manages
-- the transaction to ensure atomic commit with migration_history.

-- Step 1: Drop view that depends on news.unique_id
DROP VIEW IF EXISTS news_with_themes;

-- Step 2: Narrow unique_id back to VARCHAR(32)
ALTER TABLE news_features ALTER COLUMN unique_id TYPE VARCHAR(32);
ALTER TABLE news ALTER COLUMN unique_id TYPE VARCHAR(32);

-- Step 3: Recreate the view
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

-- Step 4: Remove legacy column and index
DROP INDEX IF EXISTS idx_news_legacy_unique_id;
ALTER TABLE news DROP COLUMN IF EXISTS legacy_unique_id;

-- Step 5: Revert schema_version
DELETE FROM schema_version WHERE version = '1.3';
