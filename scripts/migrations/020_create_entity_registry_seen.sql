-- 020_create_entity_registry_seen.sql
-- Estado da canonicalizacao por forma-de-superficie distinta (resumibilidade + auditoria).
-- O job de canonicalizacao (data-science) varre formas distintas de news_features, resolve
-- cada (surface_norm, type) uma unica vez e registra o resultado aqui para nao re-tentar
-- indefinidamente as que ficaram em 'needs_review'. Ref: data-platform#178 — Fase 3.

CREATE TABLE IF NOT EXISTS entity_registry_seen (
    surface_norm     TEXT NOT NULL,                  -- normalize(forma_canonica) — chave do resolver
    type             VARCHAR(16) NOT NULL,           -- ORG|PER|LOC|EVENT|POLICY|LAW
    status           VARCHAR(16) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'resolved', 'needs_review')),
    entity_id        VARCHAR(64) REFERENCES entity_registry(entity_id) ON DELETE SET NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    sample_unique_id VARCHAR(120),                   -- artigo exemplo (p/ escalada contextual de PER)
    last_error       TEXT,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (surface_norm, type)
);

-- Indice para varrer as pendentes/needs_review rapidamente
CREATE INDEX IF NOT EXISTS idx_entity_registry_seen_status ON entity_registry_seen (status);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_entity_registry_seen_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_entity_registry_seen_updated_at
    BEFORE UPDATE ON entity_registry_seen
    FOR EACH ROW
    EXECUTE FUNCTION update_entity_registry_seen_updated_at();
