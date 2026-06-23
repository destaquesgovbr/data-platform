-- 024_add_trend_detection_indexes.sql
-- Índices para acelerar as queries do load_snapshot() (trend-detection autoresearch).
--
-- Problema: load_snapshot() com 20 janelas temporais levava 484s no baseline e degradou
-- para 640s+/janela durante backfill heavy. As queries de embedding são o maior gargalo.
--
-- Sem CONCURRENTLY: tabelas são novas (criadas em 021/022), sem risco de lock.
-- CONCURRENTLY causava falha no test framework (aplica fora de ordem em fase 2).

-- ── 1. Cobertura das queries de embedding ──────────────────────────────────────────────────
-- Queries 3 e 4 do load_snapshot() filtram em AMBOS:
--   ne.entity_id = ANY(lista de ~425 IDs)  E  ne.published_at BETWEEN ? AND ?
--
-- Com índices separados em (entity_id) e (published_at), o planner faz bitmap AND.
-- Com este índice composto, cada entity_id tem um range scan temporal direto —
-- elimina a bitmap intersection e reduz I/O especialmente na janela de 28 dias (baseline).
CREATE INDEX IF NOT EXISTS idx_news_entities_entity_pub
    ON news_entities (entity_id, published_at);


-- ── 2. Cobertura da query de novas arestas ─────────────────────────────────────────────────
-- Query 2 do load_snapshot() filtra:
--   kind = 'co_mention' AND first_seen BETWEEN ? AND ? AND src_id = ANY(?)
--
-- O índice existente idx_entity_edges_src (src_id, kind, weight DESC) não inclui first_seen.
-- O planner usa-o para filtrar por (src_id, kind) e depois aplica o filtro temporal em memória.
-- Este índice permite range scan direto em first_seen para o tipo mais comum ('co_mention').
CREATE INDEX IF NOT EXISTS idx_entity_edges_first_seen
    ON entity_edges (first_seen, kind);
