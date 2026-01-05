# Plano: DAG Airflow para Sync PostgreSQL → HuggingFace

> **Status**: Em planejamento
> **Criado em**: 2024-12-29
> **Repositórios**: data-platform, infra

## Objetivo

Criar uma DAG Airflow 3.0 que sincroniza notícias do PostgreSQL para o dataset HuggingFace diariamente.

## Requisitos

- **Airflow 3.0** (Cloud Composer)
- **Schedule**: Diário após pipeline (6 AM UTC)
- **Escopo**: Notícias do dia anterior (`logical_date - 1 day`)
- **Error Handling**: Retry com exponential backoff
- **Sem XCom para dados**: Uma única task para evitar serialização de dados grandes

---

## Arquivos a Criar/Modificar

### Repositório data-platform

| Arquivo | Ação |
|---------|------|
| `src/data_platform/dags/sync_postgres_to_huggingface.py` | Criar |
| `src/data_platform/dags/requirements.txt` | Criar |

### Repositório infra (Terraform)

| Arquivo | Ação |
|---------|------|
| `terraform/composer_secrets.tf` | Adicionar Airflow Variable para HF token |

---

## Colunas do Dataset HuggingFace (24 campos)

```
unique_id, agency, published_at, updated_datetime, extracted_at,
title, subtitle, editorial_lead, url, content,
image, video_url, category, tags,
theme_1_level_1, theme_1_level_1_code, theme_1_level_1_label,
theme_1_level_2_code, theme_1_level_2_label,
theme_1_level_3_code, theme_1_level_3_label,
most_specific_theme_code, most_specific_theme_label,
summary
```

**Mapeamento PG → HF:**

| PostgreSQL | HuggingFace |
|------------|-------------|
| `n.image_url` | `image` |
| `t1.label` | `theme_1_level_1` (campo legado, mesmo valor de `theme_1_level_1_label`) |

---

## Arquitetura da DAG

```
┌────────────────────────────────────────┐
│  sync_news_to_huggingface (única task) │
│  - Lê do PostgreSQL                    │
│  - Converte para formato HF            │
│  - Push para HuggingFace Hub           │
└────────────────────────────────────────┘
```

**Justificativa**: Uma única task evita uso de XCom para grandes volumes de dados.

---

## Configuração do HF Token

### Abordagem: Airflow Connection via Secret Manager

O Composer já está configurado com Secret Manager Backend. Vamos criar uma Airflow Connection para o HuggingFace token.

**Uso na DAG:**
```python
from airflow.hooks.base import BaseHook

# Obter token da connection
conn = BaseHook.get_connection('huggingface_default')
hf_token = conn.password  # Token armazenado no campo password
```

**Formato da Connection:**
- **Conn Type**: HTTP
- **Conn ID**: `huggingface_default`
- **Password**: `<HF_TOKEN>`

O secret será criado via Terraform com o prefixo `airflow-connections-` para que o Composer carregue automaticamente como Connection.

---

## Dependências Python no Cloud Composer

### Abordagem: requirements.txt via GCS bucket

O Cloud Composer carrega automaticamente dependências de um arquivo `requirements.txt` no bucket GCS do ambiente.

**Arquivo**: `src/data_platform/dags/requirements.txt`

```
# Dependências Python para DAGs do Cloud Composer
# Este arquivo é sincronizado para o GCS bucket do Composer
# e as dependências são instaladas automaticamente

datasets>=2.14.0
huggingface-hub>=0.20.0
```

**Deploy**: O workflow `composer-deploy-dags.yaml` deve ser atualizado para também sincronizar o requirements.txt para o bucket do Composer em `gs://<bucket>/dags/requirements.txt`.

**Nota**: O Composer detecta mudanças no requirements.txt e reinstala as dependências automaticamente.

---

## Query PostgreSQL → HuggingFace

```sql
SELECT
    n.unique_id,
    n.agency_key as agency,
    n.published_at,
    n.updated_datetime,
    n.extracted_at,
    n.title,
    n.subtitle,
    n.editorial_lead,
    n.url,
    n.content,
    n.image_url as image,
    n.video_url,
    n.category,
    n.tags,
    t1.label as theme_1_level_1,          -- Campo legado
    t1.code as theme_1_level_1_code,
    t1.label as theme_1_level_1_label,
    t2.code as theme_1_level_2_code,
    t2.label as theme_1_level_2_label,
    t3.code as theme_1_level_3_code,
    t3.label as theme_1_level_3_label,
    tm.code as most_specific_theme_code,
    tm.label as most_specific_theme_label,
    n.summary
FROM news n
LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
WHERE n.published_at >= %s
  AND n.published_at < %s::date + INTERVAL '1 day'
ORDER BY n.published_at DESC
```

---

## Código da DAG

**Arquivo**: `src/data_platform/dags/sync_postgres_to_huggingface.py`

```python
"""
DAG para sincronizar notícias do PostgreSQL para HuggingFace.

Executa diariamente após o pipeline de scraper/enrichment.
Processa notícias do dia anterior (logical_date - 1 day).
"""

from datetime import datetime, timedelta
from collections import OrderedDict
import logging
import os

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.hooks.base import BaseHook

# Constants
DATASET_PATH = "nitaibezerra/govbrnews"
REDUCED_DATASET_PATH = "nitaibezerra/govbrnews-reduced"

# Colunas do dataset HuggingFace (ordem importante)
HF_COLUMNS = [
    "unique_id", "agency", "published_at", "updated_datetime", "extracted_at",
    "title", "subtitle", "editorial_lead", "url", "content",
    "image", "video_url", "category", "tags",
    "theme_1_level_1", "theme_1_level_1_code", "theme_1_level_1_label",
    "theme_1_level_2_code", "theme_1_level_2_label",
    "theme_1_level_3_code", "theme_1_level_3_label",
    "most_specific_theme_code", "most_specific_theme_label",
    "summary"
]


@dag(
    dag_id="sync_postgres_to_huggingface",
    description="Sincroniza notícias do PostgreSQL para HuggingFace diariamente",
    schedule="0 6 * * *",  # 6 AM UTC (após pipeline das 4 AM)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["sync", "huggingface", "postgres", "daily"],
    default_args={
        "owner": "data-platform",
        "depends_on_past": False,
        "email_on_failure": False,
        "email_on_retry": False,
        "retries": 3,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
    },
)
def sync_postgres_to_huggingface_dag():
    """
    DAG que sincroniza notícias do PostgreSQL para HuggingFace.
    """

    @task
    def sync_news_to_huggingface(logical_date=None) -> dict:
        """
        Task única que:
        1. Lê notícias do dia anterior do PostgreSQL
        2. Converte para formato HuggingFace (OrderedDict)
        3. Faz push para HuggingFace Hub usando DatasetManager

        Returns:
            dict: Estatísticas do sync
        """
        from data_platform.managers.dataset_manager import DatasetManager

        # Obter data alvo (dia anterior ao logical_date)
        target_date = (logical_date - timedelta(days=1)).strftime("%Y-%m-%d")
        logging.info(f"Iniciando sync para data: {target_date}")

        # Configurar HF_TOKEN da connection
        hf_conn = BaseHook.get_connection('huggingface_default')
        os.environ["HF_TOKEN"] = hf_conn.password

        # Query PostgreSQL
        pg_hook = PostgresHook(postgres_conn_id="postgres_default")

        query = """
            SELECT
                n.unique_id,
                n.agency_key as agency,
                n.published_at,
                n.updated_datetime,
                n.extracted_at,
                n.title,
                n.subtitle,
                n.editorial_lead,
                n.url,
                n.content,
                n.image_url as image,
                n.video_url,
                n.category,
                n.tags,
                t1.label as theme_1_level_1,
                t1.code as theme_1_level_1_code,
                t1.label as theme_1_level_1_label,
                t2.code as theme_1_level_2_code,
                t2.label as theme_1_level_2_label,
                t3.code as theme_1_level_3_code,
                t3.label as theme_1_level_3_label,
                tm.code as most_specific_theme_code,
                tm.label as most_specific_theme_label,
                n.summary
            FROM news n
            LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
            LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
            LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
            LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
            WHERE n.published_at >= %s
              AND n.published_at < %s::date + INTERVAL '1 day'
            ORDER BY n.published_at DESC
        """

        records = pg_hook.get_records(query, parameters=[target_date, target_date])
        logging.info(f"Encontrados {len(records)} registros para {target_date}")

        if not records:
            logging.warning(f"Nenhum registro encontrado para {target_date}. Pulando sync.")
            return {
                "status": "skipped",
                "target_date": target_date,
                "records_synced": 0,
            }

        # Converter para OrderedDict (formato esperado pelo DatasetManager)
        data = OrderedDict()
        for col in HF_COLUMNS:
            data[col] = []

        for record in records:
            for i, col in enumerate(HF_COLUMNS):
                value = record[i]
                # Converter datetime para string ISO
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                data[col].append(value)

        # Push para HuggingFace usando DatasetManager
        logging.info(f"Iniciando push de {len(records)} registros para HuggingFace...")
        manager = DatasetManager()
        manager.insert(data, allow_update=True)

        logging.info("=" * 60)
        logging.info("PostgreSQL → HuggingFace Sync Concluído")
        logging.info("=" * 60)
        logging.info(f"Data processada: {target_date}")
        logging.info(f"Registros sincronizados: {len(records)}")
        logging.info(f"Dataset: {DATASET_PATH}")
        logging.info("=" * 60)

        return {
            "status": "success",
            "target_date": target_date,
            "records_synced": len(records),
            "dataset_path": DATASET_PATH,
        }

    # Executar task
    sync_news_to_huggingface()


# Instanciar DAG
dag_instance = sync_postgres_to_huggingface_dag()
```

---

## Terraform (repo infra)

### Adicionar Airflow Connection para HF Token

**Arquivo**: `terraform/composer_secrets.tf`

```hcl
# =============================================================================
# HUGGINGFACE TOKEN AS AIRFLOW CONNECTION
# =============================================================================

# Airflow Connection for HuggingFace API
# Connection format: http://:password@
resource "google_secret_manager_secret" "airflow_conn_huggingface" {
  secret_id = "airflow-connections-huggingface_default"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

# Connection string using existing hf-token secret
# Format: http://:TOKEN@ (password field contains the token)
resource "google_secret_manager_secret_version" "airflow_conn_huggingface" {
  secret = google_secret_manager_secret.airflow_conn_huggingface.id

  # Airflow connection URI format for HTTP with token as password
  secret_data = format(
    "http://:%s@",
    data.google_secret_manager_secret_version.hf_token.secret_data
  )
}

# Data source to read existing hf-token
data "google_secret_manager_secret_version" "hf_token" {
  secret  = "hf-token"
  project = var.project_id
}

# IAM binding for Composer SA
resource "google_secret_manager_secret_iam_member" "composer_airflow_conn_huggingface" {
  secret_id = google_secret_manager_secret.airflow_conn_huggingface.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.composer.email}"
}
```

---

## Checklist de Implementação

### 1. Infraestrutura (repo infra)
- [ ] Adicionar Airflow Connection `huggingface_default` em `terraform/composer_secrets.tf`
- [ ] Executar `terraform plan` e `terraform apply`

### 2. DAG (repo data-platform)
- [ ] Criar arquivo `src/data_platform/dags/sync_postgres_to_huggingface.py`
- [ ] Criar `src/data_platform/dags/requirements.txt`
- [ ] Atualizar workflow `composer-deploy-dags.yaml` para sincronizar requirements.txt

### 3. Deploy e Validação
- [ ] Push para branch main (deploy automático via GitHub Actions)
- [ ] Verificar se dependências foram instaladas no Composer
- [ ] Verificar se DAG aparece no Cloud Composer
- [ ] Executar manualmente para validar
- [ ] Monitorar primeira execução agendada (6 AM UTC)

---

## Referências

- [test_postgres_connection.py](../../src/data_platform/dags/test_postgres_connection.py) - Padrão de DAG existente
- [dataset_manager.py](../../src/data_platform/managers/dataset_manager.py) - Operações HuggingFace
- [composer_secrets.tf](https://github.com/destaquesgovbr/infra/blob/main/terraform/composer_secrets.tf) - Secrets do Composer
- [composer.tf](https://github.com/destaquesgovbr/infra/blob/main/terraform/composer.tf) - Configuração do Composer
