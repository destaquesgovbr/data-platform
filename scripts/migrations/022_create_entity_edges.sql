-- 022_create_entity_edges.sql
-- Arestas agregadas cross-artigo do grafo de entidades. Recomputadas (set-based, batch) pela DAG
-- project_entity_graph a partir de news_entities (co-mencao) + agencies/entity_registry (estruturais).
-- Projetavel 1:1 para o Neo4j numa etapa posterior (Fase 6b).
-- Ref: data-platform Fase 6a (projecao em grafo das entidades).

CREATE TABLE IF NOT EXISTS entity_edges (
    src_id        VARCHAR(64) NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    dst_id        VARCHAR(64) NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    kind          VARCHAR(20) NOT NULL,                -- 'co_mention' | 'subordinate_to' | 'is_agency'
    weight        INTEGER     NOT NULL DEFAULT 0,      -- nº de artigos em co-mencao (peso da aresta)
    article_count INTEGER     NOT NULL DEFAULT 0,      -- nº de artigos distintos que sustentam a aresta
    first_seen    TIMESTAMPTZ,                         -- min(published_at) dos artigos da aresta
    last_seen     TIMESTAMPTZ,                         -- max(published_at) dos artigos da aresta
    PRIMARY KEY (src_id, dst_id, kind)
);

-- Convencao: para kind='co_mention' a aresta e NAO-DIRECIONADA e armazenada uma unica vez com
-- src_id < dst_id (ordem canonica), evitando duplicar o par (A,B)/(B,A). As arestas estruturais
-- ('subordinate_to', 'is_agency') sao DIRECIONADAS (src = filho/ORG, dst = pai/agencia).

-- Indice para "vizinhos de uma entidade por tipo, mais fortes primeiro" (relatedEntities)
CREATE INDEX IF NOT EXISTS idx_entity_edges_src ON entity_edges (src_id, kind, weight DESC);

-- Indice para travessia reversa (dst -> src) usado no 1-hop nao-direcionado e em entityNetwork
CREATE INDEX IF NOT EXISTS idx_entity_edges_dst ON entity_edges (dst_id, kind);
