# Decisões Arquiteturais (ADRs)

## ADR-001: PostgreSQL como BD principal

**Status**: Aceito (2024-12)

**Contexto**: O projeto usava HuggingFace Datasets como armazenamento principal, limitando queries complexas e joins.

**Decisão**: Migrar para PostgreSQL (Cloud SQL) como fonte de verdade, mantendo HuggingFace como canal de dados abertos.

**Consequências**: Suporte a queries SQL, FKs, índices, transações ACID. Custo operacional do Cloud SQL.

---

## ADR-002: Sync diário com HuggingFace

**Status**: Aceito (2024-12)

**Decisão**: Manter sincronização diária PG → HuggingFace via DAG Airflow para preservar o dataset público.

---

## ADR-003: Schema parcialmente normalizado

**Status**: Aceito (2024-12)

**Decisão**: Normalizar `agencies` e `themes` em tabelas separadas, mas manter campos denormalizados (`agency_key`, `agency_name`) em `news` para performance de leitura.

---

## ADR-004: Arquitetura híbrida de repos

**Status**: Aceito (2024-12)

**Decisão**: Código público em repos separados (data-platform, scraper, portal), infraestrutura em repo privado (infra).

---

## ADR-005: Migração gradual com dual-write

**Status**: Aceito (2024-12)

**Decisão**: Migrar HF → PG em 6 fases graduais com período de dual-write para validação.

---

## ADR-006: Deduplicação por content_hash

**Status**: Aceito (2026-04)

**Contexto**: O portal exibia notícias duplicadas com `unique_id` diferentes. Dois cenários identificados:
- Mutação de título (80%): mesma URL/órgão, título levemente editado entre raspagens
- Republicação cross-agency (20%): órgãos diferentes publicam o mesmo press release

**Decisão**: Estratégia em múltiplas camadas:

1. **content_hash** (SHA-256 truncado 16 hex): `normalize(title + "\n" + content)` detecta republicações cross-agency
2. **Two-phase insert no scraper**: pré-check por `(agency_key, url)` antes do INSERT; se existe, faz UPDATE preservando o `unique_id` original
3. **Unique partial index**: `UNIQUE(agency_key, url) WHERE url IS NOT NULL` previne novas duplicatas
4. **group_by no Typesense**: `group_by: 'content_hash', group_limit: 1` colapsa duplicatas na exibição do portal

**Alternativas consideradas**:
- URL-based `unique_id`: rejeitado — quebraria ~300k referências externas (Typesense, BigQuery, HuggingFace)
- Dedup apenas no frontend: paliativo, não resolve a raiz

**Consequências**:
- Zero duplicatas visuais no portal (homepage, busca, similares, temas)
- Overhead mínimo no scraper (~30 linhas, SELECT sub-ms por batch)
- BigQuery pode agrupar por `content_hash` para analytics de republicação
- Gatilho de reavaliação: se p95 de `_find_existing_by_url()` > 50ms por batch em 7 dias consecutivos

**Referências**: portal#108, scraper#36, data-platform#144, data-platform#138
