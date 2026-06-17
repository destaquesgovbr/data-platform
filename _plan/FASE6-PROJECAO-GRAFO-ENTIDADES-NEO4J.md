# Fase 6 — Projeção em grafo das entidades (Postgres-first → Neo4j)

> **STATUS: ✅ IMPLEMENTADA E EM PRODUÇÃO (2026-06-17)**
> Todas as 4 sub-fases concluídas. Grafo populado: 6.471 menções, 788 arestas (672 co_mention + 116 subordinate_to), 242 entidades distintas em 3.909 artigos. Neo4j sincronizado (242 nós + 788 arestas). DAGs rodando a cada 6h automaticamente.

> Continuação de `data-platform/_plan/EVOLUCAO-IDENTIFICADOR-ENTIDADES-NER.md`. Fases 1–5 (taxonomia, registry canônico, canonicalização linked-data, propagação, lente) estão **mergeadas e em produção**. Esta é a Fase 6, que o plano original deixou como "futuro, fora do escopo".

## Context

Hoje o modelo de entidades tem **nós** (`entity_registry`: QID Wikidata ou `dgb_*`, com `type`, `agency_key`, `extra.parent_qid`) mas **nenhuma aresta materializada**. As co-menções existem só implícitas dentro de `news_features.features.entities[].canonical_id` (JSONB, GIN-indexado). Consequências:

- O portal **não tem "entidades relacionadas"** — a página `/entidades/[id]` lista só artigos; o único "relacionado" que existe é `relatedArticles` por similaridade pgvector (artigos, não entidades).
- Não há travessia multi-hop, nem rede de co-menção, nem ferramenta de exploração para analistas/jornalistas.

**Objetivo (confirmado com o usuário):** projetar entidades+relações num grafo que sirva **três consumidores ao mesmo tempo** — (a) feature pública no portal (entidades relacionadas + visualização de rede), (b) exploração interna ad-hoc (Neo4j Browser), (c) base para recomendação/busca por proximidade no futuro.

**Estratégia (confirmada):** **Postgres primeiro, Neo4j depois.** O grafo de co-menção vive como tabelas relacionais (`news_entities` + `entity_edges`) que já habilitam "entidades relacionadas" e a visualização via SQL — **sem custo de infra**. O Neo4j sobe numa segunda etapa, alimentado por essas mesmas tabelas, quando precisarmos de travessia multi-hop / Cypher / algoritmos de grafo. Arestas iniciais = **co-menção + estruturais** (sem LLM). Hosting do Neo4j = **GCE VM padrão Typesense**.

## Arquitetura-alvo (4 sub-fases)

```
news_features.entities[] (JSONB, canonical_id)
        │  (set-based SQL, DAG periódica)
        ▼
6a │ news_entities (menções normalizadas)  ──►  entity_edges (co-menção + estruturais)
        │                                              │
        │ 6c (SQL self-join, 1-hop)                    │ 6b (sync Bolt)
        ▼                                              ▼
graphql-api: relatedEntities / entityNetwork      Neo4j (GCE VM)
        │                                          (:Entity)-[:CO_MENTIONED_WITH]-(:Entity)
        ▼ 6d                                       [:SUBORDINATE_TO] [:IS_AGENCY]
portal: "Entidades relacionadas" + rede           Browser/Cypher (exploração interna)
```

Princípio: **as chaves canônicas já são estáveis** (Fases 1–5), então 6a é puro derivar-de-dados-existentes; nada bloqueia, e o Neo4j é uma projeção 1:1 das tabelas, descartável/reconstruível.

---

## Fase 6a — Camada de arestas em Postgres (data-platform) — ✅ CONCLUÍDA

Migrações em `data-platform/scripts/migrations/` (próximo nº livre = **021**; runner `scripts/migrate.py`; aplicar via workflow `db-migrate.yaml`, **nunca** local):

- **`021_create_news_entities.sql`** (+ `_rollback`): tabela de menção normalizada (1 linha por artigo×entidade canônica), fonte limpa para arestas e para o export Neo4j.
  ```sql
  news_entities(
    unique_id    VARCHAR(120) REFERENCES news(unique_id) ON DELETE CASCADE,
    entity_id    VARCHAR(64)  REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    type         VARCHAR(16) NOT NULL,
    count        INTEGER NOT NULL DEFAULT 1,
    salience     REAL,
    published_at TIMESTAMPTZ,            -- desnormalizado de news (filtro temporal)
    PRIMARY KEY (unique_id, entity_id))
  -- índices: (entity_id), (published_at)
  ```
- **`022_create_entity_edges.sql`** (+ `_rollback`): arestas agregadas cross-artigo.
  ```sql
  entity_edges(
    src_id     VARCHAR(64) REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    dst_id     VARCHAR(64) REFERENCES entity_registry(entity_id) ON DELETE CASCADE,
    kind       VARCHAR(20) NOT NULL,     -- 'co_mention' | 'subordinate_to' | 'is_agency'
    weight     INTEGER NOT NULL DEFAULT 0,  -- nº de artigos em co-menção
    article_count INTEGER NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ, last_seen TIMESTAMPTZ,
    PRIMARY KEY (src_id, dst_id, kind))
  -- co_mention: ordem canônica src_id < dst_id (não-direcionada, sem duplicar par)
  -- índices: (src_id, kind, weight DESC), (dst_id, kind)
  ```

**População — nova DAG Composer** `data-platform/src/data_platform/dags/project_entity_graph.py` (espelha `sync_pg_to_bigquery.py` / `compute_clusters.py`; conexão via `BaseHook.get_connection("postgres_default")` ou fallback `GRAPHQL_API_URL`, como as demais DAGs). Set-based, idempotente, agendada (ex.: a cada 6h, após a canonicalização):
1. **Rebuild `news_entities`** a partir de `news_features.features->'entities'` onde `canonical_id IS NOT NULL` (`jsonb_array_elements`), join com `news` p/ `published_at`. Rebuild completo é barato; opcionalmente incremental por `news_features.updated_at`.
2. **Recompute `entity_edges` co_mention** via self-join de `news_entities` no mesmo `unique_id` (pares `a.entity_id < b.entity_id`), agregando `count(distinct unique_id)` → `weight`/`article_count` e `min/max(published_at)`. **Threshold `weight >= 2`** (descarta co-menção de artigo único → evita hairball).
3. **Arestas estruturais** (determinísticas, sem LLM): `subordinate_to` de `agencies.parent_key` (resolvido p/ `entity_registry.agency_key`) e de `entity_registry.extra->>'parent_qid'`; `is_agency` ligando entity_id ORG ao seu `agency_key`.

Decisão: a manutenção fica **na DAG (batch)**, não no feature-worker — `entity_edges` é agregado global e a canonicalização já é batch, então acoplar ao worker per-artigo não compensa.

## Fase 6b — Neo4j: infra + sync (infra + data-platform) — ✅ CONCLUÍDA

**Infra (GitOps Terraform, PR → terraform-plan → merge → terraform-apply; sem Claude attribution nos commits):**
- **`infra/terraform/neo4j.tf`** (NOVO, copiar estrutura de `typesense.tf`): `google_compute_instance` COS+Docker rodando `neo4j:5-community`; disco `pd-ssd` persistente com `prevent_destroy` montado em `/data`; `google_compute_address` (IP estático); `google_service_account` com escopo p/ Secret Manager; cloud-init busca a senha via Metadata→Secret Manager (mesmo padrão do Typesense).
- **`infra/terraform/secrets.tf`** (APPEND): `neo4j-admin-password` + `neo4j-bolt-url` (container só; valor via `gcloud secrets versions add`); IAM `secretAccessor` p/ a SA do Composer e da graphql-api.
- **`infra/terraform/variables.tf`** (APPEND): `neo4j_machine_type` (default `e2-standard-4`), `neo4j_disk_size_gb` (default 50), `neo4j_heap_gb`.
- **`infra/terraform/main.tf`** (APPEND): firewall Bolt **7687** e HTTP **7474** — `source_ranges` restrito à VPC + IP admin; **não** `0.0.0.0/0` (corrigir o débito que o Typesense tem).
- **Caveat licença:** **Neo4j Community** (GPLv3, grátis) atende Browser + Cypher + a projeção. **Bloom exige Enterprise** (licenciado) — se quiser Bloom de fato, é outra decisão (custo/licença); o plano entrega **Neo4j Browser** (que é Community) para a exploração interna.

**Sync (data-platform):**
- Adicionar `neo4j` a `pypi_packages` em `infra/terraform/composer.tf`.
- **`data-platform/src/data_platform/dags/sync_graph_to_neo4j.py`** (NOVO): lê `entity_registry` (nós) + `entity_edges` (arestas) do Postgres e faz `MERGE` idempotente no Neo4j via driver Bolt (`neo4j-bolt-url` do Secret Manager). Roda após `project_entity_graph`.
  - Nós: `(:Entity {entity_id, name, type, wikidata_id, agency_key})`; `wikidata_id` como propriedade.
  - Arestas: `[:CO_MENTIONED_WITH {weight, article_count, first_seen, last_seen}]`, `[:SUBORDINATE_TO]`, `[:IS_AGENCY]`.
  - **Escopo do 1º corte:** só nós Entity + arestas agregadas (milhares de nós — grafo compacto). `(:Article)-[:MENTIONS]->(:Entity)` (300k+ artigos) fica **opcional/janelado** numa iteração posterior, para o Neo4j ficar leve.

## Fase 6c — graphql-api (resolvers de relação) — ✅ CONCLUÍDA

`graphql-api/src/graphql_api/schema/` (Strawberry, asyncpg; lembrar JSONB→str→`json.loads`):
- **`relatedEntities(id: String!, limit: Int = 12): [RelatedEntity!]`** — lê `entity_edges` (Postgres, `src_id|dst_id = id`, kind=co_mention, order by weight desc), retorna `EntityNode` conectado + `weight`/`kind`. **1-hop não precisa de Neo4j** → entrega já com 6a, sem dependência Bolt na API.
- **`entityNetwork(id, depth = 1, limit)`** (multi-hop, p/ a viz de rede): depth≤2 via CTE recursiva em `entity_edges`; profundidades maiores → ler do Neo4j (Bolt) numa iteração posterior. Retorna `{ nodes: [EntityNode], edges: [{src,dst,weight,kind}] }`.
- Tipos novos aditivos/nullable; regenerar `docs/reference/schema.graphql` (`make docs-schema`). Resolvers em `resolvers/public_content.py` (junto de `entity`/`entitySuggestions`), datasource Postgres.

## Fase 6d — portal (entidades relacionadas + rede) — ✅ CONCLUÍDA

`portal/` — **branch → `development`** (nunca `main` durante R1):
- **`/entidades/[id]`**: nova seção **"Entidades relacionadas"** (chips/cards de `relatedEntities`, cada um linkando p/ `/entidades/[id-relacionado]`) — barata, entrega com 6a+6c. Reusar Badge/Button (regra: nada clicável nativo solto; `key` nunca por índice); esconder se vazio; cor por tipo reusando `lib/entity-types.ts`.
- **Visualização de rede** (toggle, default OFF): componente client novo (ex.: `EntityNetwork.tsx`) consumindo `entityNetwork`, ego-network da entidade. Lib de grafo a adicionar (`cytoscape` ou `react-force-graph`) — oportunidade de design (frontend-design): cap de grau de nó + `weight` mínimo p/ legibilidade; cor por tipo; clique → navega à entidade.
- urql query + codegen + **atualizar snapshot SDL** `lib/graphql/schema.graphql` (drift gate R1-01 — ver `[[project_portal_codegen_drift_gate]]`).

---

## Verificação (E2E) — ⏳ PARCIAL

> **Feito:** migrações aplicadas em prod; DAG `project_entity_graph` executou (6.471 menções, 788 arestas); Neo4j populado via `sync_graph_to_neo4j`; graphql-api e portal deployados.
> **Pendente:** Playwright `e2e/graphql --workers=1` no browser (valida `relatedEntities`/`entityNetwork` no fluxo real portal → graphql-api); Neo4j Browser via túnel SSH (`gcloud compute ssh ... -- -L 7474:localhost:7474 -L 7687:localhost:7687`).



1. **data-platform**: migrações 021/022 `--dry-run` + `migrate`; rodar `project_entity_graph` localmente contra Postgres dev → conferir `news_entities` (≈ menções canonicalizadas) e `entity_edges` (spot-check: Finep↔MCTI co-mentionados; subordinate_to de uma agência com `parent_key`). Teste de threshold (par de artigo único não vira aresta).
2. **infra**: PR → revisar `terraform-plan` (VM + disco + firewall restrito + secrets); após apply, healthcheck do container Neo4j; abrir Browser e rodar `MATCH (e:Entity)-[r:CO_MENTIONED_WITH]-(x) RETURN ... LIMIT 50`.
3. **graphql-api** (`make dev` :8000): `relatedEntities(id:"Q...")` retorna vizinhos por weight; `entityNetwork(id, depth:2)` retorna nodes+edges coerentes; `make docs-schema` sem diff inesperado.
4. **portal** (gate real = Playwright no browser, serial `--workers=1` p/ `e2e/graphql` — ver `[[feedback_e2e_graphql_workers1]]`): seção "Entidades relacionadas" aparece em `/entidades/[id]` com vizinhos clicáveis; toggle da rede liga/desliga e renderiza sem hairball.

## Riscos & gates

- **Qualidade limitada pela cobertura de canonicalização**: só menções com `canonical_id` viram arestas. A cobertura ainda é parcial (backfill 314k bloqueado pela quota diária do Bedrock). O grafo **cresce conforme o backfill avança** — começar pela fatia já canonicalizada; a DAG reprojeta a cada rebuild. Não-bloqueante, mas comunicar que o grafo inicial é parcial.
- **Hairball / performance**: threshold `weight >= 2`, cap de grau na viz, `weight` mínimo na UI.
- **Segurança Neo4j**: senha no Secret Manager, firewall Bolt/HTTP **restrito à VPC + IP admin** (não repetir o `0.0.0.0/0` do Typesense). Community = sem RBAC fino → tratar como serviço interno.
- **Drift gate R1-01** (portal): SDL aditivo/nullable; `make docs-schema` + `e2e/graphql` serial antes de mergear; atualizar snapshot.
- **Infra**: nunca `terraform`/`gcloud` infra local; só via PR + `terraform-apply`. Python sempre em venv.
- **Custo**: VM Neo4j ~US$80-120/mês — só sobe na 6b; 6a+6c+6d entregam a feature pública **sem** esse custo.

## Insight de faseamento

`entityNetwork` com `depth<=2` roda via **CTE recursiva em `entity_edges`** — ou seja, **toda a experiência do portal (entidades relacionadas + viz de rede) entrega sobre Postgres**, sem Neo4j. O Neo4j (6b) é **puramente aditivo**: exploração interna (Browser/Cypher) + travessia profunda/algoritmos de grafo no futuro. Logo o caminho crítico de valor é **6a → 6c → 6d**, e **6b** é uma trilha de infra paralela e independente.

## Implementação — log de execução (2026-06-16/17)

| PR | Repo | Status | Conteúdo |
|---|---|---|---|
| #180 | data-platform | ✅ mergeado + migrado | migrações 021+022, `jobs/graph/edges.py`, DAGs `project_entity_graph` + `sync_graph_to_neo4j` |
| #19  | graphql-api   | ✅ mergeado + deployado | resolvers `relatedEntities` + `entityNetwork`, SDL atualizado |
| #266 | portal        | ✅ mergeado em `development` | `RelatedEntities.tsx` + `EntityNetwork.tsx` (toggle, react-force-graph-2d) |
| #200 | infra         | ✅ mergeado + terraform-apply | `neo4j.tf` (GCE VM COS+Docker), firewall VPC-only, secrets |

**Pós-merge manual (2026-06-17):**
- Senha gerada e armazenada em `neo4j-admin-password` (Secret Manager, versão 1)
- `neo4j-bolt-url` + `airflow-variables-neo4j_bolt_url` configurados com `bolt://10.0.0.6:7687`
- VM `destaquesgovbr-neo4j` (zona `southamerica-east1-a`, IP interno `10.0.0.6`) iniciada; startup-script baixou `neo4j:5-community` e subiu container

**Resultado das primeiras runs:**
- `project_entity_graph`: ✅ success — 6.471 menções, 788 arestas (672 co_mention + 116 subordinate_to + 0 is_agency¹), 242 entidades, 3.909 artigos
- `sync_graph_to_neo4j`: ✅ success — 242 nós + 788 arestas no Neo4j (23s)

> ¹ `is_agency = 0` esperado no 1º corte: liga nó ORG genérico ao nó de agência quando ambos coexistem no registry — maioria das agências entrou só pelo seed.

**Gotchas corrigidos em CI (pré-existentes, não causados pela Fase 6):**
- `composer-deploy-dags.yaml` não incluía `jobs/graph` nos plugins → `ModuleNotFoundError` nas 2 primeiras runs da DAG; corrigido com commit direto em main.
- `graphql-api/tests/test_setup.py` quebrava com FastAPI 0.137 (`_IncludedRouter` sem `.path`/`.routes`); helper `_all_route_paths` tolerante adicionado.
- `data-platform/tests/integration/test_migrate_integration.py` estava vermelho na main desde Fase 1-5 (`BASELINE_SQL` sem `news_features`); corrigido.

## Orquestração (workflow + subagentes)

Execução via **Workflow** com subagentes, um por repo (dirs distintos → sem conflito de arquivos). Orquestrador (thread principal) = fino. Local-first + TDD em todos. **Nada de `terraform`/`gcloud`/merge dentro dos agentes** — o agente de infra apenas **escreve** os `.tf` e prepara o PR; deploys/migrações seguem o GitOps via CI depois.

**Workflow `fase6-entity-graph` (3 fases):**
1. **Implement-foundation** (paralelo): contrato de dados + API.
   - `data-platform` (6a): migrações `021_create_news_entities.sql` + `022_create_entity_edges.sql` (+ `_rollback`), DAG `project_entity_graph.py`, testes. Espelhar `compute_clusters.py`/migrações 015–020 existentes.
   - `graphql-api` (6c): `relatedEntities` (1-hop) + `entityNetwork` (CTE recursiva ≤2) + tipos `RelatedEntity`/`EntityNetwork`, regen `docs/reference/schema.graphql`, testes. **Retorna a SDL exata dos campos novos** (consumida pela fase seguinte).
2. **Implement-consumers** (paralelo, após foundation):
   - `portal` (6d): seção "Entidades relacionadas" em `/entidades/[id]` + `EntityNetwork.tsx` (toggle default-off, lib de grafo), query urql + codegen + snapshot SDL (drift gate), vitest. Recebe a SDL produzida pela fase 1.
   - `infra` (6b): `neo4j.tf` (copiar `typesense.tf`), `secrets.tf`/`variables.tf`/`main.tf` (firewall restrito), `neo4j` em `composer.tf`, DAG `sync_graph_to_neo4j.py` no data-platform. **Só escreve arquivos + descreve o PR.**
3. **Review** (paralelo, adversarial por repo): revisar cada diff (bugs, segurança, convenções, drift gate, SQL injection nos CTEs, hairball). Findings reais → aplicar fix.

Após o workflow: rodar testes locais por repo, abrir PRs/branches (`portal`→`development`), e seguir o GitOps para migração (`db-migrate.yaml`) e infra (`terraform-apply`). Atualiza `[[project_dgb_entity_canonicalization]]`.
