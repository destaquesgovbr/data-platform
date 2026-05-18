-- Migration 013: Nullify relative image URLs stored from Plone resolveuid paths
-- Issue: scraper#49 - webscraper stored relative paths without absolutization
-- Safety: Sets to NULL so integrity checker can re-discover absolute URL on next run

BEGIN;

UPDATE news
SET image_url = NULL
WHERE image_url IS NOT NULL
  AND image_url NOT LIKE 'http%';

COMMIT;
