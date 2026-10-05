"""DAG: Computa entity_trending_scores 4× ao dia (janela 7d vs baseline 28d).

O baseline vem de resolve_baseline_window: rolante, exceto na retomada pós-defeso
(26/10 a 29/11/2026), quando usa os 28 dias anteriores ao defeso (decisão D2).
"""

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
        import logging
        from datetime import date

        from data_platform.jobs.trend_detection.persist import upsert_trending_scores
        from data_platform.jobs.trend_detection.scorer import compute_scores
        from data_platform.jobs.trend_detection.signals import (
            TREND_DETECTION_VERSION,
            load_snapshot,
            resolve_baseline_window,
        )

        log = logging.getLogger(__name__)
        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)

        date_end = date.today()
        baseline_start, baseline_end = resolve_baseline_window(date_end)
        log.info(
            "%s: date_end=%s baseline=[%s, %s)",
            TREND_DETECTION_VERSION,
            date_end,
            baseline_start,
            baseline_end,
        )

        data = load_snapshot(
            db_url,
            date_end=date_end,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            compute_embeddings=False,
        )
        scores = compute_scores(data)
        count = upsert_trending_scores(db_url, scores, data["entity_stats"])
        return {"status": "ok", "count": count}

    run()


dag_instance = compute_entity_trending()
