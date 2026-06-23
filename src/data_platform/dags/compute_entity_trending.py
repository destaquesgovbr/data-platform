"""DAG: Computa entity_trending_scores 4× ao dia (janela 7d vs baseline 28d)."""

from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.hooks.base import BaseHook
except ImportError:
    pass


@dag(
    dag_id="compute_entity_trending",
    description="Computa trending score de entidades NER e persiste em entity_trending_scores",
    schedule="0 */6 * * *",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["gold", "entities", "trending"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
)
def compute_entity_trending():
    @task()
    def run(**context):
        from datetime import date

        from data_platform.jobs.trend_detection.persist import upsert_trending_scores
        from data_platform.jobs.trend_detection.scorer import compute_scores
        from data_platform.jobs.trend_detection.signals import load_snapshot

        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

        data = load_snapshot(db_url, date_end=date.today(), compute_embeddings=False)
        scores = compute_scores(data)
        count = upsert_trending_scores(db_url, scores, data["entity_stats"])
        return {"status": "ok", "count": count}

    run()


dag_instance = compute_entity_trending()
