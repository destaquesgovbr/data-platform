# Índice de Planejamento - Data Platform

## 📁 Planos Ativos

### [TS_SYNC_MOVED_TO_MAIN_WORKFL/](TS_SYNC_MOVED_TO_MAIN_WORKFL/)
**Status**: 🟡 Pronto para Execução  
**Descrição**: Integração do Typesense sync no main workflow + refatorações  
**Documentos**:
- [README](TS_SYNC_MOVED_TO_MAIN_WORKFL/TS_SYNC_README.md) - Começar por aqui
- [Tracking](TS_SYNC_MOVED_TO_MAIN_WORKFL/TS_SYNC_MOVED_TO_MAIN_WORKFL.md) - Plano detalhado com checkboxes
- [Execution Log](TS_SYNC_MOVED_TO_MAIN_WORKFL/TS_SYNC_EXECUTION_LOG.md) - Registro de execução
- [Quick Reference](TS_SYNC_MOVED_TO_MAIN_WORKFL/TS_SYNC_QUICK_REFERENCE.md) - Consulta rápida
- [Rollback Guide](TS_SYNC_MOVED_TO_MAIN_WORKFL/TS_SYNC_ROLLBACK.md) - Instruções de reversão

**Impacto**: Alto (modifica pipeline de produção)  
**Duração**: ~2 horas

---

## 🧩 Entidades (NER → canonicalização → grafo)

- [EVOLUCAO-IDENTIFICADOR-ENTIDADES-NER.md](EVOLUCAO-IDENTIFICADOR-ENTIDADES-NER.md) — Fases 1–5 (taxonomia, registry, canonicalização, lente) ✅ em produção
- [FASE6-PROJECAO-GRAFO-ENTIDADES-NEO4J.md](FASE6-PROJECAO-GRAFO-ENTIDADES-NEO4J.md) — Fase 6 (grafo Postgres→Neo4j) ✅ em produção
- [BACKFILL-ENTIDADES-ORQUESTRACAO.md](BACKFILL-ENTIDADES-ORQUESTRACAO.md) — 🟡 Backfill NER+canon como Cloud Run Jobs + DAGs + governador de cota 80% (Sonnet 4.6)

## 📋 Outros Documentos

- [bateria-testes-integracao.md](bateria-testes-integracao.md) - Testes de integração do pipeline

---

**Última atualização**: 2026-06-17
