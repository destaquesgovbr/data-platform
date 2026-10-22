"""DAG: Projeta o grafo de entidades em Postgres (news_entities + entity_edges).

Fase 6a. Set-based e idempotente: a cada run reconstroi news_entities a partir de
news_features.features->'entities' (so mencoes com canonical_id NAO-NULL) e recomputa
entity_edges (co-mencao + estruturais). Roda apos a canonicalizacao (batch), a cada 6h.

Antes do grafo, recalcula news.content_key (chave de quase-duplicata H5, DP-1b) dos ultimos
10 dias: e a chave que o grafo usa para contar conteudos distintos.

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

    0. **`news.content_key`** (chave de quase-duplicata H5, DP-1b): recalcula os ultimos
       10 dias (lendo 7 dias antes como contexto) e grava so o que mudou. Se falhar, o
       grafo roda assim mesmo com a chave anterior. Sem a coluna (migracao 035 pendente ou
       revertida), a task sai com aviso e o grafo conta pelo `content_hash`.
    1. **Rebuild `news_entities`** de `news_features.features->'entities'`
       (apenas `canonical_id` NAO-NULL), join `news` p/ `published_at`.
    2. **Recompute `entity_edges` co_mention** via self-join (`a.entity_id < b.entity_id`,
       ordem canonica, nao-direcionada), threshold `weight >= 2`.
    3. **Arestas estruturais** `subordinate_to` (agencies.parent_key + extra.parent_qid)
       e `is_agency` (ORG -> agencia).
    4. **`entity_stats` + `entity_graph_meta`**: artigos e conteudos distintos
       (`COALESCE(content_key, content_hash, unique_id)`) por entidade e no corpus
       (lift/PMI na graphql-api).

    Passos 1-4 numa transacao, idempotente (reconstroi do zero a cada run).
    """,
)
def project_entity_graph():
    @task
    def compute_content_keys(**context):
        """Recalcula news.content_key dos ultimos 10 dias (uma transacao, idempotente)."""
        from data_platform.jobs.graph.content_keys import run_content_keys

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        result = run_content_keys(db_url)
        logger.info("content_key recalculada: %s", result)
        return result

    # all_done: uma falha na chave nao congela o grafo (ele usa a chave anterior via COALESCE).
    @task(trigger_rule="all_done")
    def project_graph(**context):
        """Reconstroi news_entities e recomputa entity_edges (uma transacao, idempotente)."""
        from data_platform.jobs.graph.edges import project_entity_graph as run_projection

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        result = run_projection(db_url)
        logger.info("Projecao do grafo concluida: %s", result)
        return result

    compute_content_keys() >> project_graph()


dag_instance = project_entity_graph()
