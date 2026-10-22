-- 032_entity_stats.sql
-- Estatisticas por entidade e totais do corpus para o grafo de co-mencao (DP-1).
-- Republicacoes da mesma materia por varios orgaos inflam as contagens; unique_content_count
-- conta conteudos distintos pela chave de ARTICLE_CONTENT_KEY_SQL (jobs/graph/edges.py; hoje
-- COALESCE(content_hash, unique_id)). Trocar a chave nao exige migracao.
-- Recomputadas pela DAG project_entity_graph na mesma transacao do rebuild de entity_edges.
-- A graphql-api le estas tabelas via LEFT JOIN (lift/PMI, contagens deduplicadas): antes do
-- 1o run pos-migracao as colunas/linhas novas vem NULL.
-- Ref: DP-1 / graphql-api GQL-1.

-- ADD COLUMN nulo e instantaneo, mas pede ACCESS EXCLUSIVE em entity_edges: nao esperar
-- atras do rebuild da DAG (que segura a tabela durante a transacao) bloqueando leitores.
SET LOCAL lock_timeout = '10s';

-- Conteudos distintos que sustentam a aresta. NULL nas arestas subordinate_to e nas de
-- co-mencao ate o 1o run pos-migracao.
ALTER TABLE entity_edges
    ADD COLUMN IF NOT EXISTS unique_content_count INTEGER;

-- 1 linha por entidade com ao menos uma mencao em news_entities.
-- is_generic/generic_reason sao curadoria: o rebuild da DAG nao os grava nem sobrescreve.
CREATE TABLE IF NOT EXISTS entity_stats (
    entity_id            VARCHAR(64) PRIMARY KEY REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    article_count        INTEGER     NOT NULL,              -- nº de artigos distintos que mencionam
    unique_content_count INTEGER     NOT NULL,              -- nº de conteudos distintos (dedup por content_hash)
    first_seen           TIMESTAMPTZ,                       -- min(published_at) das mencoes
    last_seen            TIMESTAMPTZ,                       -- max(published_at) das mencoes
    is_generic           BOOLEAN     NOT NULL DEFAULT false,
    generic_reason       TEXT,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Totais do corpus do grafo (linha unica): artigos com ao menos uma mencao canonica em
-- news_entities e seus conteudos distintos. Denominador do lift/PMI.
CREATE TABLE IF NOT EXISTS entity_graph_meta (
    id                   SMALLINT    PRIMARY KEY CHECK (id = 1),
    total_articles       INTEGER     NOT NULL,
    total_unique_content INTEGER     NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
