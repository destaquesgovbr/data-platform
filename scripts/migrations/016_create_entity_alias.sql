-- 016_create_entity_alias.sql
-- Mapa de alias -> canonico: o resolver determinístico cacheado (coracao do "reprocessavel-sem-LLM").
-- Mencao nova -> normaliza -> lookup em entity_alias[alias_norm, type]; hit anexa entity_id sem LLM.
-- Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.

CREATE TABLE IF NOT EXISTS entity_alias (
    alias_norm  TEXT NOT NULL,                 -- forma de superficie normalizada (ver §normalization)
    type        VARCHAR(16) NOT NULL,
    entity_id   VARCHAR(64) NOT NULL REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    source      VARCHAR(24) NOT NULL,          -- 'agencies_seed'|'llm'|'wikidata'|'manual'
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (alias_norm, type)
);

-- Indice para resolver "todos os alias de uma entidade" e suportar o ON DELETE CASCADE
CREATE INDEX IF NOT EXISTS idx_entity_alias_entity_id ON entity_alias (entity_id);
