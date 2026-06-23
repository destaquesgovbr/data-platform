-- Migration 013 ROLLBACK: Remove Summary Moderation Fields
-- Data: 2026-06-23
-- Issue: #187 (Sub-issue de #176)
-- ATENÇÃO: Execute apenas se precisar reverter a migration 013

-- Dropar views primeiro (dependem das colunas)
DROP VIEW IF EXISTS news_moderation_stats;
DROP VIEW IF EXISTS news_moderation_log;

-- Dropar índices
DROP INDEX IF EXISTS idx_news_summary_blocked_at;
DROP INDEX IF EXISTS idx_news_summary_blocked;

-- Remover colunas (ATENÇÃO: dados serão perdidos!)
ALTER TABLE news
  DROP COLUMN IF EXISTS summary_blocked,
  DROP COLUMN IF EXISTS summary_blocked_reason,
  DROP COLUMN IF EXISTS summary_blocked_at;

-- Verificar que foi removido
\d news;
