"""
Gera ~158 DAGs de scraping, uma por agência gov.br.

Cada DAG:
- Roda a cada 15 minutos
- Scrape notícias da última hora (janela de segurança)
- Insere no PostgreSQL via StorageAdapter
- Retry: 2x com backoff de 5 min
- Timeout: 15 min por execução
"""
import os
from datetime import datetime, timedelta

import yaml
from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook


def _load_agencies_config() -> dict:
    """Carrega config de agências do YAML."""
    config_path = os.path.join(os.path.dirname(__file__), "config", "site_urls.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)["agencies"]


def create_scraper_dag(agency_key: str, agency_url: str):
    """Factory que cria uma DAG de scraping para uma agência."""

    @dag(
        dag_id=f"scrape_{agency_key}",
        description=f"Scrape notícias de {agency_key}",
        schedule="*/15 * * * *",
        start_date=datetime(2025, 1, 1),
        catchup=False,
        max_active_runs=1,
        tags=["scraper", "govbr", agency_key],
        default_args={
            "owner": "data-platform",
            "retries": 2,
            "retry_delay": timedelta(minutes=5),
            "retry_exponential_backoff": True,
            "max_retry_delay": timedelta(minutes=15),
            "execution_timeout": timedelta(minutes=15),
        },
    )
    def scraper_dag():

        @task
        def scrape(logical_date=None):
            """Scrape notícias da agência e insere no PostgreSQL."""
            # Bridge: extrair DATABASE_URL do Airflow connection
            hook = PostgresHook(postgres_conn_id="postgres_default")
            os.environ["DATABASE_URL"] = hook.get_uri()
            os.environ["STORAGE_BACKEND"] = "postgres"

            from data_platform.managers import StorageAdapter
            from data_platform.scrapers.scrape_manager import ScrapeManager

            # Janela: última 1 hora (com margem de segurança)
            min_date = (logical_date - timedelta(hours=1)).strftime("%Y-%m-%d")
            max_date = logical_date.strftime("%Y-%m-%d")

            storage = StorageAdapter()
            manager = ScrapeManager(storage)
            manager.run_scraper(
                agencies=[agency_key],
                min_date=min_date,
                max_date=max_date,
                sequential=True,
                allow_update=False,
            )

        scrape()

    return scraper_dag()


# Gerar DAGs dinamicamente
for key, url in _load_agencies_config().items():
    globals()[f"scrape_{key}"] = create_scraper_dag(key, url)
