# Convenção de DAGs Descentralizadas

## Contexto

O DestaquesGovBr utiliza Cloud Composer (Airflow) para orquestrar pipelines de dados. Com a extração do scraper para um repositório standalone, adotamos uma convenção de **deploy de DAGs descentralizado por subdiretório**, onde cada repositório é responsável por deployar suas próprias DAGs.

## Arquitetura

```
Cloud Composer DAGs Bucket
├── data-platform/                    ← Repo: destaquesgovbr/data-platform
│   ├── sync_postgres_to_huggingface.py
│   └── test_postgres_connection.py
├── scraper/                          ← Repo: destaquesgovbr/scraper
│   ├── scrape_agencies.py            (~155 DAGs dinâmicas)
│   ├── scrape_ebc.py
│   └── config/
│       └── site_urls.yaml
├── activitypub-server/               ← Repo: destaquesgovbr/activitypub-server
│   └── federation_publish.py
└── <futuro-repo>/                    ← Qualquer novo repo
    └── ...
```

O Airflow lê DAGs recursivamente a partir do bucket, então DAGs em subdiretórios são detectadas automaticamente.

## Como funciona

### Deploy via `gsutil rsync`

Cada repo tem seu próprio workflow `composer-deploy-dags.yaml` que faz:

```bash
gsutil rsync -r -d <local-dags-dir> <bucket>/<repo-name>/
```

O flag `-d` (delete) remove do bucket arquivos que não existem mais no source. O subdiretório garante que cada repo **só gerencia suas próprias DAGs** — um repo não pode deletar DAGs de outro.

### Estrutura do workflow

```yaml
# .github/workflows/composer-deploy-dags.yaml
env:
  COMPOSER_ENVIRONMENT: destaquesgovbr-composer
  COMPOSER_REGION: us-central1
  DAGS_LOCAL_PATH: src/data_platform/dags   # ou "dags" no scraper
  DAGS_SUBDIRECTORY: data-platform           # nome do repo

steps:
  - name: Get DAGs bucket
    run: |
      DAGS_BUCKET=$(gcloud composer environments describe ...)
      echo "dags_bucket=$DAGS_BUCKET" >> $GITHUB_OUTPUT

  - name: Deploy DAGs
    run: |
      gsutil rsync -r -d ${{ env.DAGS_LOCAL_PATH }} \
        ${{ steps.composer.outputs.dags_bucket }}/${{ env.DAGS_SUBDIRECTORY }}/
```

### DAG `owner`

Para identificar a origem de cada DAG no Airflow UI, usamos o campo `owner` nos `default_args`:

```python
default_args = {
    "owner": "data-platform",    # ou "scraper"
    ...
}
```

## Adicionando um novo repo

Para que um novo repositório deploye DAGs no Composer:

1. **Criar diretório de DAGs** no repo (ex: `dags/`)

2. **Adicionar WI binding** no repo `infra/terraform/workload-identity.tf`:
   ```hcl
   resource "google_service_account_iam_member" "github_actions_workload_identity_<repo>" {
     service_account_id = google_service_account.github_actions.name
     role               = "roles/iam.workloadIdentityUser"
     member             = "principalSet://iam.googleapis.com/${...}/attribute.repository/${var.github_organization}/<repo>"
   }
   ```

3. **Copiar workflow** `composer-deploy-dags.yaml` de um repo existente, ajustando:
   - `DAGS_LOCAL_PATH`: caminho local das DAGs
   - `DAGS_SUBDIRECTORY`: nome do subdiretório no bucket (usar nome do repo)

4. **Definir `owner`** nos `default_args` de cada DAG com o nome do repo

## Repositórios atuais

| Repo | Subdiretório | DAGs | Owner |
|------|-------------|------|-------|
| `data-platform` | `data-platform/` | sync_postgres_to_huggingface, test_postgres_connection | `data-platform` |
| `scraper` | `scraper/` | ~155 scrape_agencies + scrape_ebc | `scraper` |
| `activitypub-server` | `activitypub-server/` | federation_publish | `activitypub-server` |

## Migração (fev/2025)

Antes desta convenção, todas as DAGs eram deployadas na raiz do bucket pelo repo `data-platform`. A migração incluiu:

1. Alterar `gsutil rsync` target de `{bucket}/` para `{bucket}/data-platform/`
2. Cleanup one-time das DAGs legadas na raiz do bucket
3. Criação do repo `scraper` com deploy para `{bucket}/scraper/`

O step de cleanup legado pode ser removido dos workflows após a primeira execução bem-sucedida.
