-- 026_add_fallback_triggered.sql
-- Adiciona campo para rastrear quando fallback do scraper foi acionado.
-- Ref: destaquesgovbr/scraper#60

ALTER TABLE scrape_runs
    ADD COLUMN IF NOT EXISTS fallback_triggered BOOLEAN DEFAULT FALSE;

-- Partial index: apenas registros com fallback (otimiza queries)
CREATE INDEX IF NOT EXISTS idx_scrape_runs_fallback
    ON scrape_runs (fallback_triggered, scraped_at DESC)
    WHERE fallback_triggered = true;

-- Comentário na coluna para documentação
COMMENT ON COLUMN scrape_runs.fallback_triggered IS
    'Indica se o fallback automático (WebScraper → Plone6APIScraper) foi acionado devido a erro HTML_CHANGED';
