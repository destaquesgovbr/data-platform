-- 015_create_entity_registry.sql
-- Registro canonico de entidades (nivel "canonico" cross-artigo, projetavel para grafo Neo4j).
-- Cada linha = um no de entidade unica. QID do Wikidata quando linkado; senao "dgb_<slug-ou-ulid>".
-- Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.

-- Extensao pg_trgm: necessaria para o indice trigram de matching fuzzy em canonical_name.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS entity_registry (
    entity_id      VARCHAR(64) PRIMARY KEY,           -- QID ("Q216330") se linkado, senao "dgb_<slug-or-ulid>"
    canonical_name TEXT NOT NULL,
    type           VARCHAR(16) NOT NULL,              -- ORG|PER|LOC|EVENT|POLICY|LAW
    aliases        JSONB NOT NULL DEFAULT '[]',
    wikidata_id    VARCHAR(32),
    wikidata_url   TEXT,
    description    TEXT,
    agency_key     VARCHAR(100) REFERENCES agencies(key),
    confidence     REAL NOT NULL DEFAULT 0.0,
    provenance     VARCHAR(24) NOT NULL,              -- 'agencies_seed'|'wikidata'|'llm'|'manual'
    extra          JSONB NOT NULL DEFAULT '{}',       -- country, parent_qid, instance_of
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indices de lookup
CREATE INDEX IF NOT EXISTS idx_entity_registry_type        ON entity_registry (type);
CREATE INDEX IF NOT EXISTS idx_entity_registry_wikidata_id ON entity_registry (wikidata_id);
CREATE INDEX IF NOT EXISTS idx_entity_registry_agency_key  ON entity_registry (agency_key);

-- GIN em aliases (consulta de membership no array JSONB de formas alternativas)
CREATE INDEX IF NOT EXISTS idx_entity_registry_aliases_gin ON entity_registry USING GIN (aliases);

-- GIN trigram em canonical_name (matching fuzzy / similaridade textual)
CREATE INDEX IF NOT EXISTS idx_entity_registry_name_trgm
    ON entity_registry USING GIN (canonical_name gin_trgm_ops);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_entity_registry_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_entity_registry_updated_at
    BEFORE UPDATE ON entity_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_entity_registry_updated_at();
