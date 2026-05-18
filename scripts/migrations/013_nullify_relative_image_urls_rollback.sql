-- Rollback 013: No safe automatic rollback
-- Original values were invalid relative paths (e.g. resolveuid/...)
-- Recovery: re-scrape affected articles to populate correct absolute URLs

SELECT 'No automatic rollback available. Original values were invalid relative paths.' AS notice;
