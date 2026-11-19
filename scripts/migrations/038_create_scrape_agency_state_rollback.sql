-- Rollback for 038_create_scrape_agency_state.sql
-- Fazer o rollback do scraper que grava o estado ANTES. Sem as tabelas, o scraper novo desfaz
-- só o savepoint do estado e segue gravando scrape_runs, mas o /agencies/state responde 503 e
-- o /dispatch para. O estado (circuitos abertos, marcas d'água) se perde; reaplicar a 038
-- refaz o seed a partir de scrape_runs e news.

-- Mesmo lock_timeout da 038: o DROP TABLE pede ACCESS EXCLUSIVE nas duas tabelas.
SET LOCAL lock_timeout = '10s';

DROP TABLE IF EXISTS scrape_dispatch_meta;
DROP TABLE IF EXISTS scrape_agency_state;
