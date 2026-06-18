# Backfill & orquestração da identificação de entidades (NER + canonicalização → grafo) com governador de cota

> **STATUS: 🟡 EM IMPLEMENTAÇÃO (2026-06-17)**
> Continuação operacional de `EVOLUCAO-IDENTIFICADOR-ENTIDADES-NER.md` (Fases 1–5) e `FASE6-PROJECAO-GRAFO-ENTIDADES-NEO4J.md` (Fase 6). Aquelas entregaram o **código**; este plano entrega a **execução do backfill** sobre o acervo, sob teto de cota.

## Context

As Fases 1–6 estão **implementadas e em produção**, mas o backfill **estagnou em 11/jun**. Medição em prod (2026-06-17, psql read-only):

| Métrica (prod) | Valor |
|---|---|
| `news` total | 335.268 |
| com features | 26.925 (8,0%) |
| com entidades (NER) | 21.463 (6,4%) — maioria ainda **Haiku 3 legado** |
| re-NERados `ner-v1` (Sonnet 4.6) | 4.732 (1,4%) — janela 2026-05-12→06-17 (fatia de validação) |
| com `canonical_id` | 3.909 (1,2%) — quase todos via **gazetteer**, não LLM |
| `entity_registry_seen` | **20.724 pending** / 118 resolved / 65 needs_review |
| → das pendentes com `attempts=0` | **20.718** (nunca tentadas) |
| `entity_registry_seen.updated_at` máx | **2026-06-11 13:31** (job não roda há 6 dias) |
| grafo | 242 nós, 788 arestas, 6.471 menções, 3.909 artigos |

**Causa raiz: orquestração, não quota.** O Step B da canonicalização praticamente nunca rodou (20.718 formas com `attempts=0`). Os CLIs existem (`canonicalization_job.py`, `renew_ner_window.py`) mas são **manuais, sem empacotamento nem agendamento**.

**Modelos — confirmado empiricamente (boto3, conta 048894428441, us-east-1, 2026-06-17):**
- `us.anthropic.claude-sonnet-4-6` → ✅ invoca, retorna `usage{input_tokens,output_tokens}`
- `us.anthropic.claude-opus-4-6-v1` → ✅ invoca (config atual do canon)
- `us.anthropic.claude-opus-4-8` → ❌ **AccessDeniedException (não habilitado)**

**Decisão:** usar **Sonnet 4.6 para NER e canonicalização**. Evita dependência de Opus, simplifica o governador (um único pool de cota Sonnet, compartilhado por worker-ao-vivo + NER-backfill + canon-backfill) e é configurável por env (Opus 4.6 permanece disponível como upgrade futuro de qualidade do canon, sem mudar código). Model vars já em prod: `NER_MODEL_ID=us.anthropic.claude-sonnet-4-6`; `CANON_MODEL_ID` passa de Opus 4.6 → **Sonnet 4.6**.

**Objetivo:** produtizar e agendar os jobs de backfill sob um **governador de cota** que limita este processo a **80% da cota diária de tokens do Bedrock**, deixando ≥20% para os outros consumidores LLM. Decisões do usuário: **Cloud Run Job + DAG do Composer**; escopo **completo (incl. ~314k NER histórico)**; **grind resumível**; **teto 80%**.

## Arquitetura

CLIs de batch → **Cloud Run Jobs** (execuções longas, resumíveis, sem ack-deadline). Lógica Bedrock no **data-science**; **data-platform** agenda via **DAGs do Composer** com `CloudRunExecuteJobOperator` (provider google ≥10.14). Grafo (`project_entity_graph` + `sync_graph_to_neo4j`, 6h) **cresce sozinho** conforme `canonical_id` aumenta.

```
infra (Terraform)                 data-science (imagens + lógica)         data-platform (Composer + schema)
cloud_run_v2_job canon-backfill ◄ docker/canon-job + canonicalization_job  dag canonicalize_backfill ─┐
cloud_run_v2_job ner-backfill   ◄ docker/ner-job + backfill_ner_corpus     dag ner_backfill           ├ CloudRunExecuteJobOperator
  + SAs + secret IAM            ◄ quota_governor.py (lê ledger, decide)     migration 023 llm_daily_usage
  + IAM Composer→run.developer    + captura usage de TODA chamada Bedrock   (ledger de tokens)
  + quota env (JSON por modelo)   (jobs + worker ao vivo) → ledger
```

**Contrato fixo (para os subagentes não negociarem):**
- Tabela ledger: `llm_daily_usage(day DATE, model_id TEXT, input_tokens BIGINT, output_tokens BIGINT, PRIMARY KEY(day, model_id))`.
- Jobs: `destaquesgovbr-canon-backfill`, `destaquesgovbr-ner-backfill`; region `southamerica-east1`.
- Env dos jobs: `DATABASE_URL`, `AWS_BEDROCK_CONNECTION_URI` (Secret Manager), `NER_MODEL_ID`/`CANON_MODEL_ID`, `BEDROCK_DAILY_TOKEN_QUOTA` (JSON `{model_id: tokens/dia}`), `BACKFILL_QUOTA_FRACTION="0.8"`.
- Modelo (ambos): `us.anthropic.claude-sonnet-4-6`. `anthropic_version="bedrock-2023-05-31"`.

## Governador de cota (≤80% da cota diária) — peça central

O backfill **se auto-limita**; o worker ao vivo nunca para. Cede quando o consumo **do dia, account-wide, para o modelo** atinge `0.8 × cota_diária`.

- **Captura de tokens:** hoje `raw_meta` (llm_client.py:577) **descarta** o `usage` do Bedrock. Passar a capturar `usage.input_tokens/output_tokens` em **todas** as chamadas (NER, combinada Haiku, canon).
- **Ledger (Postgres):** `llm_daily_usage` (migração 023). **Todos os chamadores** (jobs de backfill **e** worker ao vivo) fazem `UPSERT ... += tokens`. Como os consumidores de texto são os mesmos (worker combinado Haiku, Sonnet NER, Sonnet canon), o ledger reflete o consumo real por modelo.
- **Decisão (só nos jobs):** antes de cada chamada/batch, `usado = SUM(input+output) WHERE day=current_date AND model_id=<modelo>`; se `usado ≥ 0.8 × cota(modelo)` → **parar gracioso** (exit 0; resumível amanhã). Como NER e canon usam Sonnet 4.6, ambos medem contra o **mesmo pool**; os 20% sobram para o worker ao vivo.
- **Config:** cotas reais por modelo via env (`BEDROCK_DAILY_TOKEN_QUOTA`, lidas do AWS Service Quotas — **nunca inventadas**), setadas no Terraform; `BACKFILL_QUOTA_FRACTION=0.8` configurável.
- **Rede de segurança:** manter tratamento de `ThrottlingException` (back-off + parada limpa). UPSERT atômico (`ON CONFLICT DO UPDATE SET tokens = tokens + EXCLUDED.tokens`); checagem a cada N chamadas tolera pequena ultrapassagem (margem ~78–80%).

## Work breakdown (por repo)

### A. data-science
- **`src/news_enrichment/quota_governor.py`** (novo): `record_usage(conn, model_id, in_tok, out_tok)` (UPSERT), `tokens_used_today(conn, model_id)`, `budget_exhausted(conn, model_id, quota, fraction)`. Puro/testável.
- **Captura `usage`** em `llm_client.py` (NER + combinada) e na chamada canon (`canonicalization.llm_canonicalize`/`apply_gates`) → devolve no `raw_meta` e chama `record_usage`.
- **Wire do governador** em `canonicalization_job.resolve_pending` e no driver NER (check `budget_exhausted` antes de cada forma/artigo, ou a cada N).
- **`scripts/backfill_ner_corpus.py`** (novo, ou `--from-scratch` em `renew_ner_window.py`): seleciona `news` SEM `news_llm_raw` task='ner' prompt_version='ner-v1' (cobre os ~314k sem NER), resumível, capado, ordem configurável; `_upsert_ai_features` com **INSERT-on-conflict** quando não há linha `news_features`.
- **`docker/canonicalization-job/Dockerfile`** + **`docker/ner-backfill-job/Dockerfile`**: base = enrichment-worker; `ENTRYPOINT` = shim que parseia `AWS_BEDROCK_CONNECTION_URI` → `AWS_ACCESS_KEY_ID/SECRET/REGION` discretos e `exec`uta o CLI com `"$@"`.
- **Worker ao vivo** (`worker/handler.py`): chamar `record_usage` (só escreve; não se auto-limita).
- **Config canon**: `get_canon_model_id()` continua lendo `CANON_MODEL_ID`; default de prod (Terraform) → Sonnet 4.6.
- **Fixes**: `mint_internal_id` (canonicalization.py:107) trunca slug ~52 chars + sufixo hash (evita estouro de `varchar(64)`); `poetry add httpx` (importado em wikidata_client.py:20, ausente do pyproject).
- **Testes** (Bedrock/Wikidata mockados): governador, captura de usage, driver histórico, mint bound, shim de creds.
- **CI**: 2 workflows `*-job-deploy.yaml` reusando `cloud-run-deploy.yml@v2`.

### B. infra (só escreve `.tf`; nunca apply local)
- **`terraform/canonicalization-job.tf`** + **`terraform/ner-backfill-job.tf`**: `google_cloud_run_v2_job` (region SP); env conforme contrato; `timeout` ~3600s; SA dedicada + IAM `secretAccessor` (DB + aws_bedrock secrets).
- **`terraform/variables.tf`** (append): `bedrock_daily_token_quota` (JSON/map) + `backfill_quota_fraction` (default `0.8`); ajustar `canon_model_id` default → `us.anthropic.claude-sonnet-4-6`.
- **IAM Composer→Jobs** (`composer_iam.tf`): SA do Composer com `roles/run.developer`.
- **Airflow Variables** (`composer_secrets.tf`): `canon_job_name`, `ner_job_name`, `cloud_run_jobs_region`.

### C. data-platform
- **`scripts/migrations/023_create_llm_daily_usage.sql`** (+ rollback): tabela do ledger. Aplicar via `db-migrate.yaml`.
- **`src/data_platform/dags/canonicalize_backfill.py`** + **`ner_backfill.py`**: `@dag` diário (defasados), `max_active_runs=1`, `catchup=False`; task `CloudRunExecuteJobOperator` (job/region via `Variable.get`) com `overrides` (`--since`/`--limit` guard secundário; governador é o teto primário). Sem novo módulo em `jobs/` (lógica vive na imagem).

## Orquestração com subagentes (Workflow)

1. **Foundation (paralela):** `data-science` ‖ `data-platform-schema` (migração 023) ‖ `infra` (`.tf`, write-only).
2. **Consumers:** `data-platform-dags` (2 DAGs) — usa nomes/region dos Jobs + tabela ledger do contrato.
3. **Review (paralela, adversarial por repo):** segurança (creds via Secret Manager, SA mínima), corretude do governador (race UPSERT; soma dia/modelo; parada limpa), SQL do selector histórico (índices), idempotência/resumibilidade. Findings → fix.

Pós-workflow (usuário/GitOps): testes locais; PRs; migração 023 via `db-migrate.yaml`; CI builda imagens; terraform-apply cria Jobs+IAM; composer-deploy publica DAGs; despausar e **monitorar drain** (`entity_registry_seen`, `with_canonical_id`, `llm_daily_usage`); `typesense-maintenance-sync.yaml` quando cobertura subir. Atualizar memória `[[project_dgb_entity_canonicalization]]`.

## Verificação (E2E)
1. **data-science (venv):** `pytest` (governador cap 80%, captura usage, driver histórico, mint bound); `--dry-run` do canon e NER contra DB dev; smoke do shim de creds.
2. **data-platform:** migração 023 `--dry-run` + apply; `llm_daily_usage` criada.
3. **infra:** revisar `terraform-plan` (2 Jobs, SAs, secret IAM, run.developer, quota vars). Após apply: `gcloud run jobs execute <canon> --args="--limit=20"` e checar ledger.
4. **Orquestração:** trigger manual das DAGs; medir delta `entity_registry_seen` (pending↓/resolved↑), `with_canonical_id`↑, e parada ao bater 80% (logs "budget exhausted").
5. **Grafo + portal:** `project_entity_graph` na próxima run > 242/788; Playwright serial (`e2e/graphql/entities.spec.ts`, `--workers=1`).

## Riscos & gates
- **Cota diária** = teto: governador a 80% (ledger account-wide por modelo) garante ≥20% para o worker ao vivo; jobs resumíveis ⇒ atraso não-bloqueante.
- **Race no ledger**: UPSERT atômico; checagem periódica com margem.
- **Cotas reais**: ler do AWS Service Quotas; nunca inventar. Sem valor → começar conservador, ajustar por env (sem redeploy de código).
- **Credenciais no Job**: Secret Manager; SA dedicada mínima; nunca chave em texto no `.tf`.
- **Selector histórico (314k)**: sem full-scan caro — `NOT EXISTS` sobre `news_llm_raw(unique_id,task,prompt_version)` + índice em `published_at`.
- **Infra/Composer/Python**: subagentes só escrevem arquivos; deploy via PR+CI; nunca `terraform`/`gcloud` infra local; Python sempre em venv.
- **Portal durante R1**: branch `development`, nunca `main`.
