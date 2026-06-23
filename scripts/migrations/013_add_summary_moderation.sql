-- Migration 013: Add Summary Moderation Fields
-- Data: 2026-06-23
-- Issue: #187 (Sub-issue de #176)
-- Objetivo: Adicionar campos para tracking de moderação de resumos gerados por LLM

-- Adicionar colunas de moderação à tabela news
ALTER TABLE news
  ADD COLUMN IF NOT EXISTS summary_blocked BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS summary_blocked_reason TEXT,
  ADD COLUMN IF NOT EXISTS summary_blocked_at TIMESTAMP;

-- Comentários descritivos
COMMENT ON COLUMN news.summary_blocked IS 'Flag indicando se o resumo foi bloqueado por guardrails de segurança';
COMMENT ON COLUMN news.summary_blocked_reason IS 'Razão do bloqueio (ex: "regex: CPF detectado", "llm: linguagem ofensiva")';
COMMENT ON COLUMN news.summary_blocked_at IS 'Timestamp do bloqueio';

-- Índice para monitoramento (apenas para registros bloqueados)
CREATE INDEX IF NOT EXISTS idx_news_summary_blocked
  ON news (summary_blocked)
  WHERE summary_blocked = TRUE;

-- Índice composto para auditoria (ordenado por data)
CREATE INDEX IF NOT EXISTS idx_news_summary_blocked_at
  ON news (summary_blocked_at DESC)
  WHERE summary_blocked = TRUE;

-- View para auditoria de moderação
CREATE OR REPLACE VIEW news_moderation_log AS
SELECT
  n.unique_id,
  n.title,
  n.summary_blocked_reason,
  n.summary_blocked_at,
  n.created_at,
  n.agency_key,
  n.agency_name,
  n.category,
  EXTRACT(EPOCH FROM (n.summary_blocked_at - n.created_at)) / 60 AS minutes_to_block
FROM news n
WHERE n.summary_blocked = TRUE
ORDER BY n.summary_blocked_at DESC;

COMMENT ON VIEW news_moderation_log IS 'Log de auditoria de resumos bloqueados por guardrails (ordenado por data de bloqueio)';

-- View para estatísticas de moderação (dashboard)
CREATE OR REPLACE VIEW news_moderation_stats AS
SELECT
  DATE(summary_blocked_at) AS date,
  COUNT(*) AS total_blocked,
  COUNT(DISTINCT agency_key) AS affected_agencies,
  ARRAY_AGG(DISTINCT SUBSTRING(summary_blocked_reason, 1, 50) ORDER BY summary_blocked_reason) AS unique_reasons
FROM news
WHERE summary_blocked = TRUE
  AND summary_blocked_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(summary_blocked_at)
ORDER BY date DESC;

COMMENT ON VIEW news_moderation_stats IS 'Estatísticas diárias de moderação (últimos 30 dias)';

-- Verificar estrutura
\d news;
\d+ news_moderation_log;
\d+ news_moderation_stats;
