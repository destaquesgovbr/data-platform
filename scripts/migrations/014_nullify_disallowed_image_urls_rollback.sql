-- Rollback for migration 014
-- Cannot restore original URLs; re-scraping required to rediscover them.
-- This is a no-op placeholder for consistency.

SELECT 'Rollback not possible: original image_url values were not preserved. '
       'Re-scraping affected articles will rediscover valid URLs.' AS warning;
