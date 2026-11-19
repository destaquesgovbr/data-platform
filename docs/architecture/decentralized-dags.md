# Convenção de DAGs Descentralizadas

## Contexto

O DestaquesGovBr orquestra os pipelines batch num Airflow próprio: Airflow 3.1.8 em docker compose
na VM `destaquesgovbr-airflow` (repo `infra`, `terraform/airflow.tf`). Até a Fase 7 da migração
(`infra/_plan/migrar-composer-para-airflow-proprio.md`) era o Cloud Composer, já desligado.

O deploy de DAGs é **descentralizado por subdiretório**: cada repositório publica as próprias DAGs
(e, se precisar, um pacote de plugins) numa subpasta do bucket do Airflow.

## Arquitetura

```
gs://destaquesgovbr-airflow
├── dags/
│   ├── data-platform/            ← Repo: destaquesgovbr/data-platform
│   │   ├── sync_pg_to_bigquery.py
│   │   ├── compute_trending.py
│   │   └── ...                   (12 DAGs)
│   ├── scraper/                  ← Repo: destaquesgovbr/scraper
│   │   ├── scrape_agencies.py    (uma DAG, task mapeada por agência)
│   │   ├── scrape_ebc.py
│   │   └── ...
│   ├── clipping/                 ← Repo: destaquesgovbr/clipping
│   ├── data-publishing/          ← Repo: destaquesgovbr/data-publishing
│   └── platform/                 ← Repo: destaquesgovbr/infra (airflow_heartbeat; reservado)
├── plugins/
│   ├── data_platform/            ← data-platform (módulos de jobs/ importados pelas DAGs)
│   ├── pyphen/                   ← data-platform (vendorizado; a imagem não tem)
│   └── data_publishing/          ← data-publishing
└── logs/                         ← logs das tasks (remote logging, 30 dias)
```

Na VM, o container `dag-sync` espelha `dags/` e `plugins/` em `/opt/airflow/{dags,plugins}` a cada
60 s, mantendo esse layout. O Airflow lê as DAGs recursivamente; `plugins/` fica no `sys.path`, por
isso as DAGs importam `data_platform.*`, `data_publishing.*` e `pyphen`.

## Como funciona

### Deploy via reusable workflow

Cada repo chama o reusable workflow
[`airflow-deploy-dags.yml@v3`](https://github.com/destaquesgovbr/reusable-workflows/blob/main/.github/workflows/airflow-deploy-dags.yml),
que valida as DAGs com o Airflow 3.1.8 (`py_compile` e, opcionalmente, imports) e publica com:

```bash
gcloud storage rsync --recursive --delete-unmatched-destination-objects \
  <dags_local_path>/ gs://destaquesgovbr-airflow/dags/<dags_bucket_subdir>/
```

O rsync apaga no destino o que não existe mais na origem. A subpasta garante que cada repo **só
gerencia as próprias DAGs**: um repo não apaga DAGs de outro. O workflow recusa subpasta vazia,
com `/` ou igual a `platform`.

### Estrutura do workflow

```yaml
# .github/workflows/composer-deploy-dags.yaml (nome histórico)
permissions:
  contents: read
  id-token: write

jobs:
  deploy:
    uses: destaquesgovbr/reusable-workflows/.github/workflows/airflow-deploy-dags.yml@v3
    with:
      dags_local_path: dags          # ou src/data_platform/dags
      dags_bucket_subdir: scraper    # nome do repo
      # plugins_local_path: src/<pacote>   (opcional)
```

O default de `buckets` do v3 é `destaquesgovbr-airflow`. O data-platform é a exceção: publica os
plugins num job próprio (monta `plugins/data_platform/` só com os módulos que as DAGs importam e
vendoriza o `pyphen`) e repassa a lista de buckets (`AIRFLOW_DAG_BUCKETS`) ao v3. Ver
[docs/dags/README.md](../dags/README.md#deploy).

### DAG `owner`

Para identificar a origem de cada DAG no Airflow UI, usamos o campo `owner` nos `default_args`:

```python
default_args = {
    "owner": "data-platform",    # ou "scraper"
    ...
}
```

## Adicionando um novo repo

1. **Criar diretório de DAGs** no repo (ex: `dags/`).

2. **Adicionar WI binding** no repo `infra/terraform/workload-identity.tf`:
   ```hcl
   resource "google_service_account_iam_member" "github_actions_workload_identity_<repo>" {
     service_account_id = google_service_account.github_actions.name
     role               = "roles/iam.workloadIdentityUser"
     member             = "principalSet://iam.googleapis.com/${...}/attribute.repository/${var.github_organization}/<repo>"
   }
   ```

3. **Criar o workflow** chamando o `airflow-deploy-dags.yml@v3` (exemplo acima), com
   `dags_bucket_subdir` = nome do repo.

4. **Dependências**: pacote que a DAG importa precisa estar na imagem do Airflow
   (`infra/airflow/requirements.txt`, PR no `infra`) ou ir como plugin (`plugins_local_path`).

5. **Definir `owner`** nos `default_args` de cada DAG com o nome do repo.

6. **Despausar** a DAG na UI depois do primeiro deploy: DAG nova nasce pausada. Ao despausar, o
   horário mais recente que passou roda na hora (ver o
   [runbook](../runbooks/airflow-vm.md#catch-up-ao-despausar)).

## Repositórios atuais

| Repo | Subdiretório | DAGs | Owner |
|------|-------------|------|-------|
| `data-platform` | `data-platform/` | sync_pg_to_bigquery, compute_trending, compute_entity_trending, aggregate_engagement, compute_clusters, project_entity_graph, generate_video_thumbnails, sync_umami_to_bigquery, verify_news_integrity, ner_backfill, canonicalize_backfill, enrichment_backfill | `data-platform` |
| `scraper` | `scraper/` | scrape_agencies, scrape_ebc, monitor_scraping_health, cleanup_old_scrape_runs, scraper_coverage_report | `scraper` |
| `clipping` | `clipping/` | dispatch_clippings | `clipping` |
| `data-publishing` | `data-publishing/` | sync_postgres_to_huggingface | `data-publishing` |
| `infra` | `platform/` | airflow_heartbeat | `platform` |

## Histórico

- **fev/2025**: as DAGs saíram da raiz do bucket do Composer para `{bucket}/data-platform/`, e o
  repo `scraper` passou a publicar em `{bucket}/scraper/` (`gsutil rsync -r -d`).
- **nov/2026**: migração do Composer para o Airflow próprio. Fase 3: reusable workflow v3
  publicando nos dois buckets. Fase 7: o Composer foi desligado e o deploy passou a publicar só em
  `gs://destaquesgovbr-airflow`. O `activitypub-server` (DAG `federation_publish`) foi desligado
  antes.
