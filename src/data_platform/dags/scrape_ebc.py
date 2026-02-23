"""DAG para scraping de notícias EBC (Agência Brasil, TV Brasil)."""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook


@dag(
    dag_id="scrape_ebc",
    description="Scrape notícias EBC (Agência Brasil, TV Brasil)",
    schedule="*/15 * * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["scraper", "ebc"],
    default_args={
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
)
def scrape_ebc_dag():

    @task
    def scrape_ebc(logical_date=None):
        """Scrape notícias EBC e insere no PostgreSQL."""
        hook = PostgresHook(postgres_conn_id="postgres_default")
        os.environ["DATABASE_URL"] = hook.get_uri()
        os.environ["STORAGE_BACKEND"] = "postgres"

        from data_platform.managers import StorageAdapter
        from data_platform.scrapers.ebc_scrape_manager import EBCScrapeManager

        min_date = (logical_date - timedelta(hours=1)).strftime("%Y-%m-%d")
        max_date = logical_date.strftime("%Y-%m-%d")

        storage = StorageAdapter()
        manager = EBCScrapeManager(storage)
        manager.run_scraper(min_date, max_date, sequential=True)

    scrape_ebc()


dag_instance = scrape_ebc_dag()
