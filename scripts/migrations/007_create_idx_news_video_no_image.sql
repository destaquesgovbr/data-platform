-- 007_create_idx_news_video_no_image.sql
-- Indice parcial para otimizar a query de batch de thumbnails.
-- Cobre o ORDER BY (published_at DESC, unique_id ASC) e o WHERE parcial
-- usado em jobs/thumbnail/batch.py.

CREATE INDEX IF NOT EXISTS idx_news_video_no_image
    ON news (published_at DESC, unique_id ASC)
    WHERE video_url IS NOT NULL
      AND video_url != ''
      AND (image_url IS NULL OR image_url = '');
