-- 023_create_llm_daily_usage.sql
-- Ledger de consumo de tokens do Bedrock (Anthropic), account-wide, agregado por dia x modelo.
-- Todos os chamadores LLM (worker ao vivo + jobs de backfill NER/canon) fazem UPSERT += tokens
-- a cada chamada, lendo usage.input_tokens/usage.output_tokens da resposta do Bedrock.
-- Lastreia o governador de cota: antes de cada batch, os jobs somam o consumo do dia para o
-- modelo e param graciosamente ao atingir 80% (BACKFILL_QUOTA_FRACTION) da cota diaria,
-- deixando >=20% para o worker ao vivo. A PK (day, model_id) ja serve a query SUM por dia+modelo;
-- sem indices extras. Ref: data-platform — Backfill & orquestracao de entidades (migracao 023).

CREATE TABLE IF NOT EXISTS llm_daily_usage (
    day           DATE   NOT NULL,                  -- dia (UTC) do consumo agregado
    model_id      TEXT   NOT NULL,                  -- ex.: 'us.anthropic.claude-sonnet-4-6'
    input_tokens  BIGINT NOT NULL DEFAULT 0,        -- soma dos input_tokens do dia para o modelo
    output_tokens BIGINT NOT NULL DEFAULT 0,        -- soma dos output_tokens do dia para o modelo
    PRIMARY KEY (day, model_id)
);

-- UPSERT atomico usado por todos os chamadores (acumula, nunca sobrescreve):
--   INSERT INTO llm_daily_usage (day, model_id, input_tokens, output_tokens)
--   VALUES (CURRENT_DATE, :model_id, :in, :out)
--   ON CONFLICT (day, model_id) DO UPDATE SET
--       input_tokens  = llm_daily_usage.input_tokens  + EXCLUDED.input_tokens,
--       output_tokens = llm_daily_usage.output_tokens + EXCLUDED.output_tokens;
