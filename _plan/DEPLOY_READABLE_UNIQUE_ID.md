# Plano de Deploy — unique_id legivel (Issue #43)

## Contexto

**Issue**: [data-platform#43](https://github.com/destaquesgovbr/data-platform/issues/43) — Substituir `unique_id` baseado em MD5 (hex de 32 chars) por slugs legiveis + sufixo de 6 chars (ex: `governo-anuncia-programa-habitacao_a3f2e1`).

**PRs envolvidos**:
- [scraper#21](https://github.com/destaquesgovbr/scraper/pull/21) — Novo modulo `unique_id.py` substituindo logica inline de MD5
- [data-platform#108](https://github.com/destaquesgovbr/data-platform/pull/108) — Migracao de schema VARCHAR(32)->VARCHAR(120), correcao de regex do engagement, script de migracao de dados

**Impacto**: ~300k registros existentes no PostgreSQL, ~158 DAGs de scraper, regex de engagement no BigQuery, tabelas `news` e `news_features`.

---

## 1. Analise das Mudancas

### Scraper (PR #21)
| Arquivo | Mudanca |
|---------|---------|
| `src/govbr_scraper/scrapers/unique_id.py` | **NOVO** — `slugify()`, `generate_suffix()`, `generate_readable_unique_id()` |
| `src/govbr_scraper/scrapers/scrape_manager.py` | Removido import `hashlib` e MD5 inline; agora chama `generate_readable_unique_id()` |
| `src/govbr_scraper/scrapers/ebc_scrape_manager.py` | Mesmo refactor — delega para novo modulo |
| `tests/test_unique_id.py` | **NOVO** — 38 testes unitarios (slugify, suffix, ID completo) |

**Efeito**: Todos os artigos novos raspados apos o deploy terao IDs no formato slug (max 107 chars). Artigos existentes NAO sao afetados por este PR.

### Data-Platform (PR #108)
| Arquivo | Mudanca |
|---------|---------|
| `docker/postgres/init.sql` | `unique_id VARCHAR(32)` -> `VARCHAR(120)`, adiciona `legacy_unique_id VARCHAR(32)` |
| `scripts/create_schema.sql` | Mesmas mudancas de schema, versao 1.2 -> 1.3 |
| `scripts/migrations/005_alter_unique_id_varchar.sql` | **NOVO** — ALTER TABLE com backfill e indexacao |
| `scripts/migrate_unique_ids.py` | **NOVO** — Script Python de migracao (dry-run, batch, rollback) |
| `src/data_platform/jobs/bigquery/engagement.py` | Regex `[a-f0-9]{32}` -> `[a-z0-9][a-z0-9_-]+` (aceita ambos formatos) |
| `tests/unit/test_engagement.py` | **NOVO** — 2 testes de validacao de regex |
| `tests/unit/test_migrate_unique_ids.py` | **NOVO** — 24 testes de migracao |
| `tests/unit/test_schema_consistency.py` | **NOVO** — 6 testes de schema |
| `Makefile` | Substituiu caminhos Python hardcoded por comandos `poetry run` |
| `.github/workflows/db-migrate.yaml` | **NOVO** — Workflow CI/CD para migracoes de banco via GitHub Actions |

**Efeito**: Amplia colunas do BD para aceitar IDs mais longos, preserva IDs antigos em `legacy_unique_id`, corrige regex do BigQuery para aceitar ambos formatos.

### Impacto em DAGs e Pipelines
- **DAGs do scraper** (~155 agencias + 1 EBC): Nenhuma mudanca nos arquivos de DAG, mas a API Cloud Run que elas chamam passara a produzir IDs no novo formato apos o deploy do scraper.
- **DAGs do data-platform**: Nenhuma mudanca nos arquivos de DAG; o plugin `engagement.py` deployado no Composer tera a regex atualizada.
- **Pipeline de engagement**: O job `deploy-plugins` do `composer-deploy-dags.yaml` sincroniza `jobs/bigquery/` para o bucket de plugins do Composer — isso deploya a correcao de regex.

---

## 2. Pre-requisitos para Deploy

### Validacao de Codigo
- [ ] CI do PR #108 passou (pytest, black, ruff, mypy)
- [ ] CI do PR #21 passou (166 testes, 0 regressoes)
- [ ] Ambos os PRs tem pelo menos 1 aprovacao de `miguellsfilho`

### Ordem de Dependencia (CRITICO)
```
data-platform#108 DEVE ser deployado ANTES de scraper#21
```
Motivo: Se o scraper gerar slugs > 32 chars antes do schema ser ampliado, o PostgreSQL rejeitara INSERTs com `value too long for type character varying(32)`.

### Pre-requisitos de Infraestrutura
- [ ] Instancia Cloud SQL `destaquesgovbr-postgres` (southamerica-east1) acessivel
- [ ] Nenhuma DAG de scraper em execucao (ou pausar durante a janela de manutencao)

### Permissoes

As operacoes de banco de dados (backup, migracao de schema, migracao de dados) sao executadas via **GitHub Actions** usando o workflow `db-migrate.yaml`. A service account `github-actions@inspire-7-finep.iam.gserviceaccount.com` ja possui:
- `roles/cloudsql.admin` — criar backups e gerenciar instancia
- `roles/cloudsql.client` — conectar ao banco via Cloud SQL Proxy
- Acesso ao Secret Manager (`govbrnews-postgres-connection-string`)

O operador do deploy precisa apenas de:
| Permissao | Passos | Descricao |
|-----------|--------|-----------|
| Acesso ao Composer (access token) | 2, 6, 7 | Pausar/despausar DAGs e disparar DAG runs via API |
| `roles/run.viewer` | 5 | Listar revisoes do Cloud Run para validacao |
| `roles/bigquery.user` | Validacao | Testar regex de engagement no BigQuery |
| `roles/storage.objectViewer` | Validacao | Verificar plugin de engagement no bucket do Composer |
| Permissao de merge nos repos | 3, 5 | Merge de PRs via GitHub CLI |

> **Nota**: A API do Cloud Run (`destaquesgovbr-scraper-api`) so aceita invocacao da service account `destaquesgovbr-composer@inspire-7-finep.iam.gserviceaccount.com` (role `roles/run.invoker`). O health check direto do Passo 7 deve ser validado indiretamente via DAG run do Airflow.

### Builds / Imagens
- **Scraper**: Nova imagem Docker construida automaticamente pelo `scraper-api-deploy.yaml` ao merge no `main`
- **Plugins do data-platform**: Deployados via `composer-deploy-dags.yaml` ao merge no `main`
- Nao e necessaria nova imagem Docker para workers do data-platform (mudanca de schema e apenas no BD)

---

## 3. Passos do Deploy

> **Nota sobre Airflow**: O Composer esta rodando **Airflow 3**, que usa a API `/api/v2/` (a `/api/v1/` foi removida). A autenticacao usa **access token** (`gcloud auth print-access-token`), nao identity token.

### Passo 1: Pausar DAGs do Scraper

**Objetivo**: Evitar novos INSERTs durante a janela de migracao.

```bash
# Obter URL do webserver Airflow do Composer
AIRFLOW_URL=$(gcloud composer environments describe destaquesgovbr-composer \
  --location=southamerica-east1 \
  --format="value(config.airflowUri)" \
  --project=inspire-7-finep)

# Access token para Airflow (Composer 3 usa access token, nao identity token)
TOKEN=$(gcloud auth print-access-token)

# Listar DAGs do scraper ativas
curl -s -H "Authorization: Bearer $TOKEN" \
  "$AIRFLOW_URL/api/v2/dags?tags=scraper&only_active=true&limit=200" | \
  jq '.dags[] | .dag_id'

# Pausar todas as DAGs do scraper
for dag_id in $(curl -s -H "Authorization: Bearer $TOKEN" \
  "$AIRFLOW_URL/api/v2/dags?tags=scraper&only_active=true&limit=200" | \
  jq -r '.dags[].dag_id'); do
  echo "Pausando $dag_id..."
  curl -s -X PATCH -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"is_paused": true}' \
    "$AIRFLOW_URL/api/v2/dags/$dag_id"
done
```

**Validacao**: Confirmar que todas as DAGs do scraper mostram `is_paused: true` na UI do Airflow.

---

### Passo 2: Merge e Deploy do data-platform PR #108

**Objetivo**: Deployar migracao de schema, correcao de regex do engagement, script de migracao e workflow `db-migrate.yaml`.

```bash
# Merge do PR #108 via GitHub CLI
cd /l/disk0/mauriciom/Workspace/destaquesgovbr/data-platform
gh pr merge 108 --squash --delete-branch
```

Isso dispara automaticamente:
1. **`composer-deploy-dags.yaml`** — sincroniza DAGs + deploya `jobs/bigquery/engagement.py` como plugin do Composer

```bash
# Monitorar execucao dos workflows
gh run list --workflow=composer-deploy-dags.yaml --limit=3
gh run watch  # acompanhar a execucao mais recente
```

**Validacao**: Workflow completa com status verde. Verificar plugin de engagement deployado:

```bash
# Verificar regex atualizada no bucket do Composer
gsutil cat "gs://southamerica-east1-destaque-227e22da-bucket/plugins/data_platform/jobs/bigquery/engagement.py" | \
  grep -o "REGEXP_EXTRACT.*"
```
Esperado: regex contem `[a-z0-9][a-z0-9_-]+` (e nao `[a-f0-9]{32}`).

---

### Passo 3: Executar Migracao de Schema via CI/CD

**Objetivo**: Ampliar colunas `unique_id` e adicionar `legacy_unique_id`. O workflow `db-migrate.yaml` cuida de: criar backup automatico, conectar ao banco via Cloud SQL Proxy, executar o SQL e validar o resultado.

```bash
# Disparar o workflow de migracao de schema
gh workflow run db-migrate.yaml \
  -f migration=005_alter_unique_id_varchar.sql
```

O workflow executa automaticamente:
1. **Valida** que o arquivo SQL existe
2. **Cria backup** on-demand do banco antes de qualquer mudanca
3. **Executa o SQL** via Cloud SQL Proxy com `ON_ERROR_STOP=1`
4. **Valida** schema version e largura das colunas

```bash
# Acompanhar execucao
gh run watch
```

**Validacao**: Job Summary do workflow mostra:
- Backup criado com status `SUCCESSFUL`
- Schema version: `1.3`
- `unique_id`: VARCHAR(120)
- `legacy_unique_id`: VARCHAR(32)

---

### Passo 4: Executar Migracao de Dados via CI/CD (dry-run primeiro)

**Objetivo**: Migrar ~300k registros existentes de MD5 para slugs legiveis, preservando originais em `legacy_unique_id`.

#### 4a. Dry-run — gera CSV sem modificar o banco

```bash
gh workflow run db-migrate.yaml \
  -f migration=005_alter_unique_id_varchar.sql \
  -f data_migration=true \
  -f data_migration_mode=dry-run
```

> **Nota**: O passo de SQL migration e idempotente (usa `IF NOT EXISTS` e `ON CONFLICT DO NOTHING`), entao rodar novamente nao causa problemas.

**Validacao**: Baixar o artefato `migration-dry-run` do workflow e revisar o CSV:
- Conversoes de slug razoaveis
- Nenhuma colisao detectada
- Nenhuma violacao de tamanho (>120 chars)

```bash
# Baixar CSV do dry-run
gh run download --name migration-dry-run
head -20 migration_dry_run.csv
wc -l migration_dry_run.csv
```

#### 4b. Executar a migracao de dados

```bash
gh workflow run db-migrate.yaml \
  -f migration=005_alter_unique_id_varchar.sql \
  -f data_migration=true \
  -f data_migration_mode=migrate \
  -f batch_size=1000
```

```bash
# Acompanhar execucao
gh run watch
```

**Validacao**: Job Summary do workflow mostra:
- `total` = `with_legacy` (todas as linhas com backfill)
- `new_format` = `total` (todas convertidas)
- Orphaned FK in news_features: 0

---

### Passo 5: Merge e Deploy do scraper PR #21

**Objetivo**: Deployar nova geracao de IDs legiveis na API do scraper no Cloud Run.

```bash
cd /l/disk0/mauriciom/Workspace/destaquesgovbr/scraper
gh pr merge 21 --squash --delete-branch
```

Isso dispara:
1. **`scraper-api-deploy.yaml`** — builda imagem Docker, faz push para Artifact Registry, deploya no Cloud Run

```bash
# Monitorar deploy
gh run list --workflow=scraper-api-deploy.yaml --limit=3
gh run watch  # acompanhar a execucao mais recente
```

**Validacao**:

```bash
# Verificar que nova revisao do Cloud Run esta servindo
gcloud run revisions list \
  --service=destaquesgovbr-scraper-api \
  --region=southamerica-east1 \
  --project=inspire-7-finep \
  --limit=3
```

Esperado: Ultima revisao mostra 100% do trafego.

---

### Passo 6: Despausar DAGs do Scraper

**Objetivo**: Retomar raspagem normal com o novo formato de ID.

```bash
TOKEN=$(gcloud auth print-access-token)

for dag_id in $(curl -s -H "Authorization: Bearer $TOKEN" \
  "$AIRFLOW_URL/api/v2/dags?tags=scraper&limit=200" | \
  jq -r '.dags[].dag_id'); do
  echo "Despausando $dag_id..."
  curl -s -X PATCH -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"is_paused": false}' \
    "$AIRFLOW_URL/api/v2/dags/$dag_id"
done
```

**Validacao**: DAGs aparecem ativas na UI do Airflow e comecam a agendar execucoes.

---

### Passo 7: Verificar Fluxo Ponta a Ponta

**Objetivo**: Confirmar que um ciclo completo scrape->insert funciona com os novos IDs.

```bash
# Disparar manualmente uma DAG de scraper para teste
TOKEN=$(gcloud auth print-access-token)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' \
  "$AIRFLOW_URL/api/v2/dags/scrape_presidencia/dagRuns"
```

Aguardar ~2 minutos e verificar o resultado do DAG run na UI do Airflow. Se completar com sucesso, a API do scraper esta funcionando com os novos IDs.

> **Nota**: O health check direto da API do scraper (`curl $SCRAPER_URL/health`) requer a service account do Composer (`roles/run.invoker`). Para validar a saude da API, use o resultado do DAG run acima.

---

## 4. Validacoes Pos-Deploy

### Verificacoes no Airflow

```bash
# Verificar DAG runs com falha na ultima hora
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$AIRFLOW_URL/api/v2/dagRuns?state=failed&start_date_gte=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)&limit=50" | \
  jq '.dag_runs | length'
```

Esperado: 0 falhas.

### Verificacao do Engagement no BigQuery

```bash
# Verificar que a regex do engagement aceita ambos formatos de ID
bq query --use_legacy_sql=false \
  "SELECT REGEXP_EXTRACT('/artigos/governo-anuncia-programa_a3f2e1', r'/artigos/([a-z0-9][a-z0-9_-]+)')"
```

Esperado: Retorna `governo-anuncia-programa_a3f2e1`.

### Saude do Cloud Run

A API do scraper (`destaquesgovbr-scraper-api`) so aceita invocacao via service account do Composer. Para verificar a saude:

```bash
# Verificar que a revisao mais recente esta ativa e servindo trafego
gcloud run revisions list \
  --service=destaquesgovbr-scraper-api \
  --region=southamerica-east1 \
  --project=inspire-7-finep \
  --limit=3

# Verificar logs recentes por erros
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="destaquesgovbr-scraper-api" AND severity>=ERROR' \
  --project=inspire-7-finep \
  --limit=10 \
  --freshness=1h
```

---

## 5. Plano de Rollback

### Cenario A: Migracao de schema falha (Passo 3)

O workflow `db-migrate.yaml` cria backup automaticamente antes de executar o SQL. Para restaurar:

```bash
# Listar backups recentes
gcloud sql backups list --instance=destaquesgovbr-postgres --project=inspire-7-finep --limit=3
# Anotar o BACKUP_ID do backup "pre-migration-005_alter..."

gcloud sql backups restore <BACKUP_ID> \
  --restore-instance=destaquesgovbr-postgres \
  --project=inspire-7-finep
```

### Cenario B: Migracao de dados produz resultados incorretos (Passo 4)

```bash
# Usar o workflow com modo rollback
gh workflow run db-migrate.yaml \
  -f migration=005_alter_unique_id_varchar.sql \
  -f data_migration=true \
  -f data_migration_mode=rollback
```

Isso restaura `unique_id` a partir de `legacy_unique_id` para todos os registros migrados.

### Cenario C: Scraper produz IDs quebrados (apos Passo 5)

```bash
# 1. Pausar DAGs do scraper imediatamente (mesmo procedimento do Passo 1)

# 2. Reverter Cloud Run para revisao anterior
PREV_REVISION=$(gcloud run revisions list \
  --service=destaquesgovbr-scraper-api \
  --region=southamerica-east1 \
  --project=inspire-7-finep \
  --format="value(metadata.name)" \
  --limit=2 | tail -1)

gcloud run services update-traffic destaquesgovbr-scraper-api \
  --to-revisions=$PREV_REVISION=100 \
  --region=southamerica-east1 \
  --project=inspire-7-finep

# 3. Reverter o merge do scraper
cd /l/disk0/mauriciom/Workspace/destaquesgovbr/scraper
git revert <sha-do-merge-commit>
git push origin main
# Workflow vai redeployar a versao anterior

# 4. Despausar DAGs apos rollback
```

### Cenario D: Regex do engagement quebra (apos Passo 2)

```bash
# Reverter PR #108 e redeployar
cd /l/disk0/mauriciom/Workspace/destaquesgovbr/data-platform
git revert <sha-do-merge-commit>
git push origin main
# Workflow vai redeployar o engagement.py antigo

# OU: Override manual do plugin
gsutil cp <engagement.py-antigo> \
  "gs://southamerica-east1-destaque-227e22da-bucket/plugins/data_platform/jobs/bigquery/engagement.py"
```

---

## 6. Riscos e Pontos de Atencao

| Risco | Severidade | Mitigacao |
|-------|------------|-----------|
| **Violacao da ordem de deploy** — scraper antes da migracao de schema | **CRITICO** | Sequenciamento estrito: data-platform primeiro, scraper depois. Pausar DAGs durante a janela. |
| **Colisoes na migracao de dados** — dois titulos diferentes gerando mesmo slug+sufixo | Media | Script de migracao tem deteccao de colisoes. Dry-run primeiro para identificar conflitos. |
| **Desalinhamento de FK em news_features** — migracao atualiza `news.unique_id` mas `news_features.unique_id` tambem precisa ser atualizado | **ALTO** | Script de migracao trata AMBAS as tabelas (drop FK, update, re-create FK). Workflow valida orphaned FKs apos migracao. |
| **Tempo longo de migracao** — ~300k registros em batches | Media | Usar `--batch-size 1000`. Estimativa ~5-10 min. DAGs do scraper pausadas durante a janela. |
| **Regex do BigQuery muito ampla** — nova regex `[a-z0-9][a-z0-9_-]+` pode capturar segmentos de URL que nao sao artigos | Baixa | Clausula `WHERE url_path LIKE '/artigos/%'` limita o escopo. Testar com URLs de exemplo. |
| **Indice Typesense desatualizado** — Typesense tem IDs antigos em cache | Media | Apos migracao, disparar recarga completa via `gh workflow run typesense-full-reload.yaml` |
| **Sync do dataset HuggingFace** — sync diario as 6 AM UTC vai publicar novos IDs | Baixa | Consumidores do dataset HF devem lidar com ambos formatos. Comunicar mudanca previamente. |
| **Roteamento de URLs no Portal** — portal usa `unique_id` nas rotas `/artigos/{id}` | **ALTO** | Verificar que o portal aceita ambos formatos de ID. Redirects 301 de IDs legados (issue separada conforme #43). |

### Janela de Manutencao Recomendada

- **Quando**: Periodo de baixo trafego (ex: dia de semana 22:00-01:00 BRT / 01:00-04:00 UTC)
- **Duracao**: ~30 minutos (reduzido com CI/CD automatizado)
- **Comunicacao**: Notificar equipe no Slack antes de iniciar

### Acompanhamento Pos-Migracao (tarefas separadas)
1. Disparar recarga completa do Typesense: `gh workflow run typesense-full-reload.yaml`
2. Monitorar DAG de sync com HuggingFace as 6 AM UTC do dia seguinte
3. Monitorar pipeline de metricas de engagement por 48 horas
4. Redirects 301 no portal (rastreado em issue separada)
