-- 037_add_scrape_runs_articles_new.sql
-- Conta só as notícias realmente novas de cada chamada de scraping.
--
-- articles_saved soma inserções e atualizações (a fase 1 do insert atualiza toda linha que
-- casa por (agency_key, url)), então infla com re-raspagens: a EBC relê o dia inteiro a cada
-- execução e o fallback Plone 6 parte de known_urls vazio. articles_new vem do RETURNING da
-- fase de inserção e articles_saved mantém o significado de "linhas gravadas".
--
-- Aditiva e nullable: só metadados no Postgres 15. O INSERT atual do scraper nomeia as
-- colunas, então segue funcionando. Aplicar ANTES do deploy do scraper que grava a coluna:
-- sem ela todo INSERT em scrape_runs falha (o erro só é logado) e o monitor perde as
-- execuções de todas as agências.
-- Ref: scraper/_plan/rearquitetura-ingestao.md (Passo 1, item 5)

-- ADD COLUMN nulo é instantâneo, mas pede ACCESS EXCLUSIVE em scrape_runs, mantido até o
-- COMMIT (inclusive durante a varredura do CREATE INDEX abaixo): não esperar atrás de
-- transações longas, enfileirando o INSERT do scraper e as leituras do monitor. Sem o lock em
-- 10s a migração falha inteira (nada fica aplicado) e é só repetir.
SET LOCAL lock_timeout = '10s';

ALTER TABLE scrape_runs
    ADD COLUMN IF NOT EXISTS articles_new INTEGER;

-- Espelha idx_scrape_runs_success_articles (008) para a checagem de agências sem notícias
-- (find_stale_agencies / monitor_scraping_health) feita sobre articles_new.
CREATE INDEX IF NOT EXISTS idx_scrape_runs_success_articles_new
    ON scrape_runs (agency_key, scraped_at DESC)
    WHERE status = 'success' AND articles_new > 0;

COMMENT ON COLUMN scrape_runs.articles_new IS
    'Linhas realmente inseridas em news por esta chamada de scraping (RETURNING da fase de inserção; com allow_update=true, só as de xmax = 0). Diferente de articles_saved, que soma inserções e atualizações. NULL nas linhas anteriores à migração 037 (e nas de um scraper que ainda não preenche a coluna): não medido, não zero.';
