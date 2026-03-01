# Proposta: Arquitetura Event-Driven para o Pipeline DGB

## Contexto

### Estado Atual do Pipeline

O pipeline DGB processa ~300k noticias de 159 sites governamentais brasileiros. A maioria dos jobs ja foi migrada do GitHub Actions para DAGs Airflow, restando apenas o sync Typesense no GH Actions. O fluxo atual e batch/cron:

```
Scraper (160 DAGs, cada 15min)
  -> Cloud Run scraper-api
    -> INSERT PostgreSQL
      -> Enrichment DAG (cada 10min, 200/batch, Bedrock)
        -> UPDATE PostgreSQL (temas + summary)
          -> Embeddings DAG (diario 5h, Cloud Run embeddings-api)
            -> UPDATE PostgreSQL (vetores 768-dim)
              -> Typesense Sync (diario 4h, GitHub Actions)
                -> Typesense index
                  -> HuggingFace Sync DAG (diario 6h)
                    -> Parquet upload
```

**Problema**: Latencia de ate 24h entre scraping e disponibilidade no portal. Cada etapa roda em schedule fixo, independente de haver dados novos. O Composer roda DAGs de enrichment/embeddings mesmo quando nao ha noticias pendentes.

### Objetivo

Converter as etapas downstream (enrichment, embeddings, typesense sync) de batch para **processamento por eventos via Pub/Sub + Cloud Run**, mantendo o scraping no Airflow como trigger. Resultado: latencia de ~15 segundos do scraping ao portal.

---

## Arquitetura Proposta

### Fluxo Event-Driven

```
Airflow DAGs (cron 15min)
  -> Cloud Run scraper-api
    -> INSERT PostgreSQL (RETURNING unique_id)
    -> PUBLISH "dgb.news.scraped"
          |
          +---> [enrichment-worker] Cloud Run
          |     subscribe "dgb.news.scraped"
          |     -> Bedrock classify + summary
          |     -> UPDATE PostgreSQL
          |     -> PUBLISH "dgb.news.enriched"
          |               |
          |               +---> [typesense-sync-worker] Cloud Run
          |               |     subscribe "dgb.news.enriched"
          |               |     -> Upsert Typesense (com temas, sem embedding)
          |               |
          |               +---> [embeddings-worker] Cloud Run
          |                     subscribe "dgb.news.enriched"
          |                     -> Gerar embedding 768-dim
          |                     -> UPDATE PostgreSQL
          |                     -> PUBLISH "dgb.news.embedded"
          |                               |
          |                               +---> [typesense-sync-worker]
          |                                     subscribe "dgb.news.embedded"
          |                                     -> Update Typesense (add embedding)
          |
          +---> HuggingFace Export (mantido como DAG diaria)
```

### Decisao: Scraper publica diretamente (nao CDC)

O scraper ja controla os INSERTs e usa `ON CONFLICT DO NOTHING`. Publicar apos INSERT bem-sucedido e simples e evita a complexidade de CDC (Debezium/pg_notify). Se o publish falhar, o artigo ja esta no PostgreSQL e sera capturado pelo job de reconciliacao.

---

## Topics e Subscriptions

### Topics Pub/Sub

| Topic | Publisher | Trigger | Retencao |
|-------|-----------|---------|----------|
| `dgb.news.scraped` | scraper-api | Novo artigo inserido no PG | 7 dias |
| `dgb.news.enriched` | enrichment-worker | Artigo classificado com temas | 7 dias |
| `dgb.news.embedded` | embeddings-worker | Embedding gerado | 7 dias |

### Subscriptions (Push para Cloud Run)

| Subscription | Topic | Subscriber | Ack Deadline | Retry |
|-------------|-------|-----------|-------------|-------|
| `dgb.news.scraped--enrichment` | scraped | enrichment-worker | 600s | 10s-600s, max 10 tentativas |
| `dgb.news.enriched--typesense` | enriched | typesense-sync-worker | 120s | 10s-300s, max 5 |
| `dgb.news.enriched--embeddings` | enriched | embeddings-worker | 600s | 30s-600s, max 5 |
| `dgb.news.embedded--typesense-update` | embedded | typesense-sync-worker | 120s | 10s-300s, max 5 |

### Dead-Letter Queues

Cada subscription tem um DLQ topic (`*-dlq`). Mensagens que falham apos max tentativas vao para o DLQ. Alerta quando DLQ > 0 mensagens.

### Schema das Mensagens

**`dgb.news.scraped`**:
```json
{
  "unique_id": "mec-2026-02-27-titulo",
  "agency_key": "mec",
  "published_at": "2026-02-27T14:30:00Z",
  "scraped_at": "2026-02-27T15:00:00Z"
}
```

**`dgb.news.enriched`**:
```json
{
  "unique_id": "mec-2026-02-27-titulo",
  "enriched_at": "2026-02-27T15:02:00Z",
  "most_specific_theme_code": "01.02.03",
  "has_summary": true
}
```

**`dgb.news.embedded`**:
```json
{
  "unique_id": "mec-2026-02-27-titulo",
  "embedded_at": "2026-02-27T15:05:00Z",
  "embedding_dim": 768
}
```

Atributos comuns: `trace_id` (UUID), `event_version` ("1.0").

---

## Servicos Cloud Run

### 1. Scraper API (modificacao — repo `scraper`)

**Mudanca**: Apos INSERT bem-sucedido, publicar mensagem no Pub/Sub.

**Arquivo**: `scraper/src/govbr_scraper/storage/postgres_manager.py`
- Modificar `insert()` para usar `RETURNING unique_id` e obter IDs inseridos
- Publicar cada ID para `dgb.news.scraped`
- **Graceful degradation**: Se publish falhar, logar erro mas NAO falhar o scrape

**Nova dependencia**: `google-cloud-pubsub` no `pyproject.toml`
**Nova env var**: `PUBSUB_TOPIC_NEWS_SCRAPED`

### 2. Enrichment Worker (novo — repo `data-science`)

**Tipo**: Cloud Run com push subscription
**Endpoint**: `POST /process` (recebe push do Pub/Sub)

**Fluxo**:
1. Decodificar mensagem, extrair `unique_id`
2. Buscar artigo do PostgreSQL
3. Chamar Bedrock (Claude Haiku) para classificacao + summary
4. UPDATE PostgreSQL com theme_ids + summary
5. Publicar `dgb.news.enriched`
6. Retornar HTTP 200 (ACK)

**Backpressure Bedrock**: `max_instance_count = 3`, `max_instance_request_concurrency = 10` -> max ~30 requests simultaneos. Se Bedrock throttle, retornar HTTP 500 e Pub/Sub faz retry com backoff.

**Reutiliza**: `NewsClassifier`, `update_news_enrichment()` do modulo `news_enrichment`

**Specs**: 1 vCPU, 1Gi RAM, timeout 900s, scale 0-3

### 3. Embeddings Worker (novo — repo `embeddings`)

**Tipo**: Cloud Run com push subscription de `dgb.news.enriched`

**Fluxo**:
1. Extrair `unique_id`
2. Buscar title + summary do PostgreSQL
3. Chamar Embeddings API (`/generate`)
4. UPDATE PostgreSQL `content_embedding`
5. Publicar `dgb.news.embedded`

**Reutiliza**: `EmbeddingGenerator` do modulo `embeddings_client`

**Specs**: 1 vCPU, 1Gi RAM, timeout 600s, scale 0-2

### 4. Typesense Sync Worker (novo — repo `data-platform`)

**Tipo**: Cloud Run com 2 push subscriptions (enriched + embedded)

**Fluxo**:
1. Extrair `unique_id`
2. Buscar dados completos do PostgreSQL
3. Upsert no Typesense

**Micro-batching**: Acumular ate 50 mensagens ou 10s antes de flush (batch upsert e mais eficiente)

**Reutiliza**: `prepare_document()`, `index_documents()` do modulo `typesense`

**Specs**: 1 vCPU, 512Mi RAM, timeout 300s, scale 0-3

---

## O que fica no Airflow vs. Pub/Sub

| Componente | Atual | Proposto | Motivo |
|-----------|-------|----------|--------|
| Scraper scheduling | 160 DAGs Airflow | **Fica no Airflow** | Cron e o forte do Airflow |
| Enrichment | DAG cada 10min | **Pub/Sub + Cloud Run** | Event-driven mais eficiente que polling |
| Embeddings | DAG diaria | **Pub/Sub + Cloud Run** | Real-time apos enrichment |
| Typesense Sync | GitHub Actions diario | **Pub/Sub + Cloud Run** | Near-real-time no portal |
| HuggingFace Export | DAG diaria | **Fica no Airflow** | Export batch por natureza |
| Reconciliacao | N/A | **Nova DAG Airflow** | Safety net para eventos perdidos |

---

## Tratamento de Erros

### Idempotencia

Todos os servicos sao idempotentes (safe para re-delivery):
- **Enrichment**: Checar `most_specific_theme_id IS NOT NULL` antes de processar
- **Embeddings**: Checar `content_embedding IS NOT NULL`
- **Typesense**: Upsert e inerentemente idempotente

### Poison Messages

Artigos que falham consistentemente (conteudo vazio, idioma errado):
1. Apos 3 falhas Bedrock, setar `classification_status = 'failed'` no PG
2. ACK a mensagem (evitar DLQ infinito)
3. DAG semanal revisa `WHERE classification_status = 'failed'`

### DAG de Reconciliacao

DAG diaria (meia-noite) para capturar eventos perdidos:
- Query `WHERE most_specific_theme_id IS NULL AND published_at > NOW() - INTERVAL '2 days'`
- Publicar no `dgb.news.scraped` para reprocessamento

---

## Backlog de 289k Artigos

**NAO publicar 289k mensagens de uma vez.** Estrategia:

1. Manter a DAG `enrich_news_llm` rodando durante a migracao (200/batch, ~28.800/dia)
2. Apos resolver o rate limit do Bedrock (issue data-science#17), processar o backlog pela DAG batch
3. Somente novos artigos fluem pelo Pub/Sub
4. Quando backlog zerar, desativar a DAG batch

---

## Latencia Esperada (Happy Path)

```
t=0:00  DAG scrape_mec trigga
t=0:02  scraper-api busca gov.br/mec, encontra 3 artigos
t=0:05  INSERT 3 artigos no PG + publish 3 msgs
t=0:06  enrichment-worker recebe push
t=0:08  Bedrock classifica + gera summary
t=0:08  UPDATE PG + publish dgb.news.enriched
t=0:09  typesense-sync-worker recebe + upsert (sem embedding)
t=0:09  embeddings-worker recebe push
t=0:11  Embedding API gera vetor 768-dim
t=0:12  UPDATE PG + publish dgb.news.embedded
t=0:13  typesense-sync-worker atualiza doc com embedding

Total: ~13 segundos do scrape ao portal (vs ~24 horas hoje)
```

---

## Custo Incremental

| Componente | Custo Mensal |
|-----------|-------------|
| Pub/Sub (~120k msgs/mes) | ~$0.05 |
| Cloud Run enrichment-worker | ~$5-10 |
| Cloud Run embeddings-worker | ~$3-5 |
| Cloud Run typesense-sync-worker | ~$2-3 |
| **Total adicional** | **~$10-18/mes** |

Custo desprezivel para obter processamento near-real-time. Potencial economia no Composer com menos DAGs consumindo workers.

---

## Infra Terraform (novos recursos)

### Novos arquivos no repo `infra/terraform/`

| Arquivo | Conteudo |
|---------|---------|
| `pubsub.tf` | Topics (scraped, enriched, embedded) + DLQ topics + subscriptions com push config + retry + DLQ policy |
| `enrichment-worker.tf` | Cloud Run service + SA + IAM (pubsub publisher/subscriber, secret accessor, sql client) |
| `embeddings-worker.tf` | Cloud Run service + SA + IAM |
| `typesense-sync-worker.tf` | Cloud Run service + SA + IAM |
| `pubsub-iam.tf` | Permissoes: scraper publica em scraped, workers publicam nos respectivos topics, Pub/Sub SA invoca Cloud Run |

### Modificacoes

| Arquivo | Mudanca |
|---------|---------|
| `scraper-api.tf` | Adicionar env var `PUBSUB_TOPIC_NEWS_SCRAPED`, IAM pubsub.publisher |
| `variables.tf` | Novas vars para topic names se necessario |

---

## Migracao em 4 Fases

### Fase 1: Infraestrutura (1-2 semanas)
- Provisionar Pub/Sub topics, subscriptions e DLQ via Terraform
- IAM roles para SAs
- Deploy Cloud Run services (apenas health endpoint)
- **Zero mudanca de comportamento**

### Fase 2: Dual-Write no Scraper (1 semana)
- Scraper publica no `dgb.news.scraped` apos INSERT
- **Todas as DAGs continuam rodando** (enrichment, embeddings)
- Validar que eventos estao fluindo via metricas do topic

### Fase 3: Workers Go Live (2-3 semanas)
- Deploy enrichment-worker, embeddings-worker, typesense-sync-worker
- 1 semana em "shadow mode": workers processam mas resultados comparados com DAGs
- Desativar DAGs de enrichment e embeddings
- Desativar Typesense sync do GitHub Actions
- DAG de reconciliacao ativa como safety net

### Fase 4: Cleanup (1 semana)
- Remover DAGs desativadas dos repos
- Tunar scaling, retry, batching com base em metricas observadas
- Dashboards e alertas
- Documentar nova arquitetura

---

## Observabilidade

### Metricas e Alertas

| Metrica | Fonte | Alerta |
|---------|-------|--------|
| Mensagens nao-acked | `pubsub.googleapis.com/subscription/num_undelivered_messages` | > 1000 por 30min |
| DLQ count | Mesmo metrica nos DLQ topics | > 0 por 15min |
| Latencia scrape-to-portal | Custom metric (timestamps) | p95 > 10min |
| Bedrock throttle rate | Cloud Run logs | > 10% requests |
| Cloud Run error rate | `run.googleapis.com/request_count` | > 5% por 10min |

### Dashboards
1. **Pipeline Health**: Fluxo de mensagens por topic, latencias
2. **Backlog Monitor**: Artigos pendentes de enrichment/embedding/indexacao
3. **Cost Monitor**: Custos Pub/Sub + Cloud Run

---

## Vinculo com Epics

- **Epic docs#28**: Arquitetura Pub/Sub (principal)
- **Epic docs#17**: Modernizacao LLM / Bedrock (enrichment-worker)
- **Epic docs#25**: Modernizacao Tecnica (migracao geral)
