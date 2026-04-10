-- 008_create_scrape_runs.sql
-- Tabela para rastrear resultados de execucao do scraper por agencia.
-- Permite deteccao de falhas consecutivas, agencias sem noticias, e relatorios de cobertura.
-- Ref: destaquesgovbr/data-platform#73, destaquesgovbr/scraper#28

CREATE TABLE IF NOT EXISTS scrape_runs (
    id SERIAL PRIMARY KEY,
    agency_key VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,              -- 'success', 'error'
    error_category VARCHAR(50),               -- ErrorCategory enum value
    error_message TEXT,
    articles_scraped INTEGER DEFAULT 0,
    articles_saved INTEGER DEFAULT 0,
    execution_time_seconds REAL,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Consultas por agencia ordenadas por data (falhas consecutivas, historico)
CREATE INDEX IF NOT EXISTS idx_scrape_runs_agency_scraped
    ON scrape_runs (agency_key, scraped_at DESC);

-- Consultas por status (cobertura, relatorios)
CREATE INDEX IF NOT EXISTS idx_scrape_runs_status
    ON scrape_runs (status, scraped_at DESC);

-- Filtro por janela temporal + particao por agencia (find_consecutive_failures)
CREATE INDEX IF NOT EXISTS idx_scrape_runs_scraped_agency
    ON scrape_runs (scraped_at DESC, agency_key);

-- Consultas de agencias sem noticias (find_stale_agencies)
CREATE INDEX IF NOT EXISTS idx_scrape_runs_success_articles
    ON scrape_runs (agency_key, scraped_at DESC)
    WHERE status = 'success' AND articles_saved > 0;
