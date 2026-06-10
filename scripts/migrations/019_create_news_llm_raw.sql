-- 019_create_news_llm_raw.sql
-- Armazenamento append-only das respostas cruas do LLM (reprocessabilidade):
-- permite re-parse sem re-chamar o Bedrock. prompt_hash = idempotencia / "o prompt mudou?".
-- Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.

CREATE TABLE IF NOT EXISTS news_llm_raw (
    id            BIGSERIAL PRIMARY KEY,
    unique_id     VARCHAR(120) NOT NULL REFERENCES news(unique_id) ON DELETE CASCADE,
    task          VARCHAR(32) NOT NULL,        -- 'ner'|'enrichment'|...
    model_id      TEXT NOT NULL,
    prompt_version VARCHAR(32) NOT NULL,
    prompt_hash   CHAR(64) NOT NULL,
    raw_response  JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_llm_raw_unique_id_task ON news_llm_raw (unique_id, task);
CREATE INDEX IF NOT EXISTS idx_news_llm_raw_prompt_version ON news_llm_raw (prompt_version);
