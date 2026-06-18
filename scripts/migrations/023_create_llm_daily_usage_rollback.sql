-- 023_create_llm_daily_usage_rollback.sql
-- Rollback: remove a tabela llm_daily_usage (ledger de consumo de tokens do Bedrock).

DROP TABLE IF EXISTS llm_daily_usage;
