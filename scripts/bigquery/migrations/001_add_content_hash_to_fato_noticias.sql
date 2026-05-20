-- Adds content_hash column to fato_noticias for deduplication tracking.
-- Ref: PR #153 (deduplicacao por content_hash)
ALTER TABLE `inspire-7-finep.dgb_gold.fato_noticias`
ADD COLUMN IF NOT EXISTS content_hash STRING;
