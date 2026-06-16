-- 021_create_news_entities.sql
-- Mencao normalizada de entidade: 1 linha por artigo x entidade canonica.
-- Derivada (set-based, batch) de news_features.features->'entities' onde canonical_id NAO e nulo.
-- Fonte limpa para as arestas de co-mencao (entity_edges) e para o export Neo4j.
-- Ref: data-platform Fase 6a (projecao em grafo das entidades).

CREATE TABLE IF NOT EXISTS news_entities (
    unique_id    VARCHAR(120) NOT NULL REFERENCES news(unique_id) ON DELETE CASCADE,
    entity_id    VARCHAR(64)  NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    type         VARCHAR(16)  NOT NULL,               -- ORG|PER|LOC|EVENT|POLICY|LAW (copiado da mencao)
    count        INTEGER      NOT NULL DEFAULT 1,     -- nº de mencoes da entidade no artigo
    salience     REAL,                                -- saliencia da mencao (quando disponivel)
    published_at TIMESTAMPTZ,                         -- desnormalizado de news (filtro temporal das arestas)
    PRIMARY KEY (unique_id, entity_id)
);

-- Indice para "todos os artigos de uma entidade" e suporte ao ON DELETE CASCADE
CREATE INDEX IF NOT EXISTS idx_news_entities_entity_id     ON news_entities (entity_id);

-- Indice para filtro/ordenacao temporal (janelas de co-mencao, recencia)
CREATE INDEX IF NOT EXISTS idx_news_entities_published_at  ON news_entities (published_at);
