"""DAG: manutenção diária de news_features.

- aggregate_and_sync: pageviews do BigQuery -> view_count em news_features.
- fill_flesch_ptbr (DP-1c): completa readability_flesch_ptbr nas linhas tocadas nos últimos 3
  dias (updated_at) que têm content e não têm a chave. O feature-worker grava a chave em todo
  artigo que processa; enrichment_backfill e ner-backfill criam/reescrevem linhas sem ela.
  Disparo manual com `--conf '{"flesch_lookback_days": null}'` varre a tabela inteira.

As tasks são independentes: uma falha no BigQuery não segura o Flesch, e vice-versa.
"""

import os
from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.hooks.base import BaseHook
    from airflow.models import Variable
except ImportError:
    pass


@dag(
    dag_id="aggregate_engagement",
    description="Aggregate portal pageviews from BigQuery and sync view_count to PG news_features",
    schedule="0 8 * * *",  # Daily at 8 AM UTC
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["gold", "features", "engagement"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
)
def aggregate_engagement_dag():
    @task()
    def aggregate_and_sync(**context):
        from data_platform.jobs.bigquery.engagement import (
            batch_upsert_engagement,
            fetch_engagement_metrics,
        )

        project_id = Variable.get("gcp_project_id")
        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

        metrics_df = fetch_engagement_metrics(project_id, days=30)
        if metrics_df.empty:
            return {"status": "no_data", "count": 0}

        graphql_url = os.environ.get("GRAPHQL_API_URL")
        if graphql_url:
            from data_platform.clients.graphql_client import GraphQLClient
            from data_platform.jobs.bigquery.engagement import (
                batch_upsert_engagement_via_graphql,
            )

            with GraphQLClient(graphql_url) as gql_client:
                count = batch_upsert_engagement_via_graphql(gql_client, metrics_df)
        else:
            count = batch_upsert_engagement(db_url, metrics_df)
        return {"status": "ok", "count": count}

    @task(execution_timeout=timedelta(minutes=30))
    def fill_flesch_ptbr(**context):
        """Preenche readability_flesch_ptbr onde falta (janela por updated_at)."""
        from data_platform.jobs.features.flesch_ptbr_fill import (
            LOOKBACK_DAYS,
            run_fill_flesch_ptbr,
        )

        dag_run = context.get("dag_run")
        conf = (getattr(dag_run, "conf", None) or {}) if dag_run else {}
        lookback_days = conf.get("flesch_lookback_days", LOOKBACK_DAYS)

        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)
        return run_fill_flesch_ptbr(db_url, lookback_days=lookback_days)

    aggregate_and_sync()
    fill_flesch_ptbr()


dag_instance = aggregate_engagement_dag()
