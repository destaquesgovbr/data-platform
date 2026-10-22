-- 035_add_news_content_key.sql
-- Chave de quase-duplicata de conteudo (DP-1b). O content_hash (009/010) so junta textos
-- identicos e o conteudo embute as URLs de imagem/link de cada orgao: o hash quase nao pega
-- republicacoes entre orgaos. content_key guarda o unique_id do lider do grupo de
-- quase-duplicatas (regra H5), calculado em lote por jobs/graph/content_keys.py (DAG
-- project_entity_graph, ultimos 10 dias a cada run; backfill na 036).
-- NULL = artigo sem quase-duplicata (ou ainda nao calculado): os leitores usam
-- COALESCE(n.content_key, n.content_hash, n.unique_id) (ARTICLE_CONTENT_KEY_SQL e graphql-api),
-- e os espacos de chave nao colidem (unique_id do lider x 16 hex do hash).
-- Sem indice: nenhum leitor filtra por content_key, e sem indice na coluna o UPDATE da chave
-- pode ser HOT (nao reescreve as entradas dos 14 indices de news, inclusive o HNSW).
-- Ref: DP-1b / graphql-api GQL-1b; ~/dgb-runs/dedup_near_dup_report_2026-10-21.md.

-- ADD COLUMN nulo e instantaneo, mas pede ACCESS EXCLUSIVE em news: nao esperar atras de
-- transacoes longas (backfills, rebuild do grafo) bloqueando leitores e o scraper.
SET LOCAL lock_timeout = '10s';

ALTER TABLE news ADD COLUMN IF NOT EXISTS content_key TEXT;
