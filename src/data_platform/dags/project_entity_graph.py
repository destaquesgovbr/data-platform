"""DAG: Projeta o grafo de entidades em Postgres (news_entities + entity_edges).

Fase 6a. Set-based e idempotente: a cada run reconstroi news_entities a partir de
news_features.features->'entities' (so mencoes com canonical_id NAO-NULL) e recomputa
entity_edges (co-mencao + estruturais). Roda apos a canonicalizacao (batch), a cada 6h.

Espelha compute_clusters.py / sync_pg_to_bigquery.py: conexao via
BaseHook.get_connection("postgres_default").
"""

import logging
from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.hooks.base import BaseHook
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dag(
    dag_id="project_entity_graph",
    description="Rebuild news_entities e recompute entity_edges (co-mencao + estruturais) a partir de news_features",
    schedule="0 */6 * * *",  # a cada 6h (apos a canonicalizacao batch)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "entities", "graph"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Projeta o grafo de entidades (Fase 6a)

    1. **Rebuild `news_entities`** de `news_features.features->'entities'`
       (apenas `canonical_id` NAO-NULL), join `news` p/ `published_at`.
    2. **Recompute `entity_edges` co_mention** via self-join (`a.entity_id < b.entity_id`,
       ordem canonica, nao-direcionada), threshold `weight >= 2`.
    3. **Arestas estruturais** `subordinate_to` (agencies.parent_key + extra.parent_qid)
       e `is_agency` (ORG -> agencia).

    Tudo numa transacao, idempotente (reconstroi do zero a cada run).
    """,
)
def project_entity_graph():
    @task
    def project_graph(**context):
        """Reconstroi news_entities e recomputa entity_edges (uma transacao, idempotente)."""
        from data_platform.jobs.graph.edges import project_entity_graph as run_projection

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        result = run_projection(db_url)
        logger.info("Projecao do grafo concluida: %s", result)
        return result

    project_graph()


dag_instance = project_entity_graph()
