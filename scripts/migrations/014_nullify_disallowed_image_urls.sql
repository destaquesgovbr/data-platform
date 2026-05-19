-- Migration 014: Nullify image URLs with domains outside the SSRF allowlist
-- These URLs are rejected by the scraper's /verify/integrity endpoint,
-- causing the entire batch to fail with 422.
-- Setting to NULL allows the integrity checker to re-discover valid URLs.

BEGIN;

UPDATE news
SET image_url = NULL
WHERE image_url IS NOT NULL
  AND image_url NOT LIKE 'https://www.gov.br/%'
  AND image_url NOT LIKE 'https://agenciabrasil.ebc.com.br/%'
  AND image_url NOT LIKE 'https://imagens.ebc.com.br/%'
  AND image_url NOT LIKE 'https://memoria.ebc.com.br/%'
  AND image_url NOT LIKE 'https://tvbrasil.ebc.com.br/%'
  AND image_url NOT LIKE 'https://live.staticflickr.com/%'
  AND image_url NOT LIKE 'https://storage.googleapis.com/destaquesgovbr-thumbnails/%';

COMMIT;
