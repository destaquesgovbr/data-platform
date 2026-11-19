-- 038_create_scrape_agency_state.sql
-- Estado por agência da ingestão de notícias: a fonte única de verdade para o despacho, o
-- disjuntor, a janela por marca d'água, o monitoramento e o painel.
--
-- scrape_agency_state tem 1 linha por agency_key (gov.br de site_urls.yaml e EBC de
-- ebc_urls.yaml do scraper). Quem escreve é o scraper-api, na mesma transação do INSERT em
-- scrape_runs (record_scrape_run) e no /dispatch. scrape_dispatch_meta é o chave-valor do
-- despachante (recálculo diário das faixas, reconciliador).
--
-- Sem FK para agencies, como scrape_runs: ansn e povosindigenas são ativas no scraper e não
-- estão em agencies. Sem trigger de updated_at: o scraper grava a coluna em todo upsert.
--
-- O seed no fim cria as linhas das agências vistas em scrape_runs nos últimos 7 dias, com a
-- faixa pela taxa de notícias. É idempotente (ON CONFLICT DO NOTHING): reaplicar não mexe no
-- estado já gravado pelo scraper.
--
-- Aplicar ANTES do deploy do scraper que grava o estado. Sem a tabela o scraper desfaz só o
-- savepoint do estado e segue gravando scrape_runs, mas o disjuntor e a marca d'água não
-- funcionam.
-- Ref: scraper/_plan/rearquitetura-ingestao.md (Passo 2) e o desenho dos Passos 2–4 (§1).

-- Padrão das 032/035/037. As tabelas são novas e o seed só lê scrape_runs e news (ACCESS
-- SHARE, compatível com os INSERTs do scraper). O limite só atua atrás de quem segura ACCESS
-- EXCLUSIVE nelas, como outra migração: aí a 038 falha inteira (nada fica aplicado) em vez de
-- enfileirar o scraper atrás dela, e é só repetir.
SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS scrape_agency_state (
    agency_key                      TEXT PRIMARY KEY,
    tier                            TEXT NOT NULL DEFAULT 'h2'
                                    CHECK (tier IN ('m30', 'h2', 'h6', 'd1')),
    poll_interval_minutes           INTEGER NOT NULL DEFAULT 120 CHECK (poll_interval_minutes > 0),
    rate_ewma_per_day               DOUBLE PRECISION,
    tier_updated_at                 TIMESTAMPTZ,
    next_due_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    boost_until                     TIMESTAMPTZ,
    last_dispatched_at              TIMESTAMPTZ,
    last_attempt_at                 TIMESTAMPTZ,   -- início da última tentativa
    last_success_at                 TIMESTAMPTZ,   -- marca d'água: início da última tentativa bem-sucedida que cobriu até hoje (BRT)
    last_new_article_at             TIMESTAMPTZ,
    consecutive_permanent_failures  INTEGER NOT NULL DEFAULT 0,
    consecutive_transient_failures  INTEGER NOT NULL DEFAULT 0,
    failure_streak_started_at       TIMESTAMPTZ,   -- início da sequência atual de falhas (qualquer tipo)
    circuit_state                   TEXT NOT NULL DEFAULT 'closed'
                                    CHECK (circuit_state IN ('closed', 'open', 'half_open')),
    circuit_opened_at               TIMESTAMPTZ,
    circuit_failed_probes           INTEGER NOT NULL DEFAULT 0,
    last_error_category             TEXT,
    last_error_message              TEXT,          -- truncado a 500 caracteres
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seleção das vencidas no /dispatch (next_due_at <= now + 7 min).
CREATE INDEX IF NOT EXISTS idx_scrape_agency_state_next_due ON scrape_agency_state (next_due_at);

CREATE TABLE IF NOT EXISTS scrape_dispatch_meta (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE scrape_agency_state IS
    'Estado da ingestão por agência (1 linha por agency_key do scraper, gov.br e EBC): faixa e intervalo de raspagem, próxima raspagem, marca d''água, falhas seguidas e disjuntor. Escrito pelo scraper-api na mesma transação de scrape_runs e pelo /dispatch. Sem FK para agencies.';
COMMENT ON COLUMN scrape_agency_state.tier IS
    'Faixa de raspagem pela taxa de notícias: m30 (>= 5/dia, 30 min), h2 (>= 1, 2 h), h6 (>= 0,2, 6 h), d1 (< 0,2, 1x por dia). Recalculada 1x por dia pelo /dispatch, com histerese de 20%.';
COMMENT ON COLUMN scrape_agency_state.poll_interval_minutes IS
    'Intervalo da faixa, em minutos (30, 120, 360 ou 1440). O efetivo cai pela metade enquanto boost_until > agora, só nas faixas h2, h6 e d1.';
COMMENT ON COLUMN scrape_agency_state.rate_ewma_per_day IS
    'Notícias por dia: média móvel exponencial com meia-vida de 7 dias sobre os 28 dias BRT completos anteriores a hoje, por news.published_at, com 0 nos dias sem notícia. rate = sum(n_d * w_d) / sum(w_d), w_d = 0.5 ^ (idade_d / 7), idade 0 = ontem.';
COMMENT ON COLUMN scrape_agency_state.next_due_at IS
    'Quando a agência vence: início da tentativa + intervalo efetivo - 5 min; com o circuito aberto, a próxima sonda (2 h, 6 h, 24 h e depois a cada 24 h).';
COMMENT ON COLUMN scrape_agency_state.boost_until IS
    'Até quando o intervalo fica pela metade, depois de uma raspagem com notícia nova (6 h). NULL = sem boost.';
COMMENT ON COLUMN scrape_agency_state.last_success_at IS
    'Marca d''água da janela: início da última tentativa bem-sucedida que cobriu até hoje (BRT). A próxima janela começa em (last_success_at em BRT - 1 h).date, limitada a hoje - 7. Tentativas com janela explícita (backfill) não a movem. NULL = sem histórico (janela ontem->hoje).';
COMMENT ON COLUMN scrape_agency_state.failure_streak_started_at IS
    'Início da sequência atual de falhas, de qualquer tipo. Erro passageiro abre o circuito quando a sequência passa de 24 h. NULL depois de um sucesso.';
COMMENT ON COLUMN scrape_agency_state.circuit_state IS
    'Disjuntor: closed; open (2 erros permanentes seguidos ou 24 h de erro passageiro; a agência não é raspada até a sonda vencer); half_open (sonda em andamento).';
COMMENT ON COLUMN scrape_agency_state.circuit_failed_probes IS
    'Sondas que falharam desde a abertura do circuito; escolhe o atraso da próxima (2 h, 6 h, 24 h).';
COMMENT ON COLUMN scrape_agency_state.last_error_message IS
    'Mensagem do último erro, truncada a 500 caracteres. last_error_category e last_error_message ficam depois de um sucesso (histórico).';
COMMENT ON TABLE scrape_dispatch_meta IS
    'Chave-valor do despachante de raspagem (/dispatch do scraper-api), por exemplo tiers_recomputed_on: o dia BRT do último recálculo das faixas.';

-- Seed: 1 linha por agency_key de scrape_runs dos últimos 7 dias, sem sobrescrever o que já
-- existir. Agência ativa que não aparece ali entra pelo ensure_rows do scraper.
--   last_attempt_at      max(scraped_at)
--   last_success_at      max(scraped_at) das execuções com sucesso, no histórico todo
--                        (90 dias de retenção): é a marca d'água real, mesmo de uma agência
--                        que só falha há mais de 7 dias
--   last_error_*         da última execução, se ela falhou; senão NULL
--   rate_ewma_per_day    EWMA de 28 dias, 0 sem notícia na janela
--   tier e intervalo     >= 5 m30/30; >= 1 h2/120; >= 0,2 h6/360; senão d1/1440
--   tier_updated_at e next_due_at = NOW(); contadores 0; circuito fechado
--
-- Custo: news é lida só na faixa de published_at da janela (idx_news_published_at, ~6,6 mil
-- linhas em 28 dias) e agrupada por agency_key; os limites são expressões estáveis, usáveis
-- como chave do índice. scrape_runs: idx_scrape_runs_scraped_agency para as chaves de 7 dias
-- e idx_scrape_runs_agency_scraped para a última execução e o último sucesso de cada uma.
WITH janela AS (
    SELECT (NOW() AT TIME ZONE 'America/Sao_Paulo')::date AS hoje
),
pesos AS (
    -- Denominador: os pesos dos 28 dias (idade 0 = ontem ... 27). Dia sem notícia entra com
    -- n = 0, então só pesa aqui; somar os pesos uma vez equivale a preencher os zeros.
    SELECT SUM(POWER(0.5::float8, idade / 7.0::float8)) AS total
    FROM generate_series(0, 27) AS idade
),
noticias_por_dia AS (
    SELECT n.agency_key,
           (n.published_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
           COUNT(*) AS qtd
    FROM news AS n
    -- [hoje - 28, hoje) em BRT: os 28 dias completos anteriores a hoje.
    WHERE n.published_at >= ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date - 28)::timestamp
                            AT TIME ZONE 'America/Sao_Paulo'
      AND n.published_at <  ((NOW() AT TIME ZONE 'America/Sao_Paulo')::date)::timestamp
                            AT TIME ZONE 'America/Sao_Paulo'
      AND n.agency_key IS NOT NULL
    GROUP BY n.agency_key, dia
),
taxa AS (
    SELECT d.agency_key,
           SUM(d.qtd * POWER(0.5::float8, (j.hoje - 1 - d.dia) / 7.0::float8)) / p.total
               AS por_dia
    FROM noticias_por_dia AS d
    CROSS JOIN janela AS j
    CROSS JOIN pesos AS p
    GROUP BY d.agency_key, p.total
),
agencias AS (
    SELECT DISTINCT agency_key
    FROM scrape_runs
    WHERE scraped_at >= NOW() - INTERVAL '7 days'
),
semente AS (
    SELECT a.agency_key,
           ultima.scraped_at AS last_attempt_at,
           sucesso.scraped_at AS last_success_at,
           COALESCE(t.por_dia, 0) AS taxa,
           CASE WHEN ultima.status = 'error' THEN ultima.error_category END
               AS last_error_category,
           CASE WHEN ultima.status = 'error' THEN LEFT(ultima.error_message, 500) END
               AS last_error_message
    FROM agencias AS a
    CROSS JOIN LATERAL (
        SELECT r.scraped_at, r.status, r.error_category, r.error_message
        FROM scrape_runs AS r
        WHERE r.agency_key = a.agency_key
        ORDER BY r.scraped_at DESC, r.id DESC
        LIMIT 1
    ) AS ultima
    LEFT JOIN LATERAL (
        SELECT r.scraped_at
        FROM scrape_runs AS r
        WHERE r.agency_key = a.agency_key AND r.status = 'success'
        ORDER BY r.scraped_at DESC
        LIMIT 1
    ) AS sucesso ON TRUE
    LEFT JOIN taxa AS t ON a.agency_key = t.agency_key
),
faixa AS (
    SELECT s.*,
           CASE WHEN s.taxa >= 5 THEN 'm30'
                WHEN s.taxa >= 1 THEN 'h2'
                WHEN s.taxa >= 0.2 THEN 'h6'
                ELSE 'd1'
           END AS tier
    FROM semente AS s
)
INSERT INTO scrape_agency_state (
    agency_key, tier, poll_interval_minutes, rate_ewma_per_day, tier_updated_at, next_due_at,
    last_attempt_at, last_success_at, last_error_category, last_error_message
)
SELECT f.agency_key,
       f.tier,
       CASE f.tier WHEN 'm30' THEN 30 WHEN 'h2' THEN 120 WHEN 'h6' THEN 360 ELSE 1440 END,
       f.taxa,
       NOW(),
       NOW(),
       f.last_attempt_at,
       f.last_success_at,
       f.last_error_category,
       f.last_error_message
FROM faixa AS f
ON CONFLICT (agency_key) DO NOTHING;
