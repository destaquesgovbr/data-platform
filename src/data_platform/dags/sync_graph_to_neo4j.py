"""DAG: Sincroniza a projecao de grafo de entidades para o Neo4j (Fase 6b).

Le entity_registry (nos) + entity_edges (arestas agregadas) do Postgres e faz MERGE
idempotente no Neo4j via driver Bolt. Roda APOS project_entity_graph (que reconstroi
as tabelas), entao o grafo Neo4j espelha o estado mais recente da projecao Postgres.

1o corte: so nos :Entity + arestas agregadas (sem nos :Article). Grafo compacto
(milhares de nos) para exploracao via Browser/Cypher.

Espelha project_entity_graph.py / sync_pg_to_bigquery.py:
- Postgres via BaseHook.get_connection("postgres_default").
- Config Neo4j via Airflow Variable "neo4j_bolt_url" (Secret Manager backend),
  com fallback para env vars (NEO4J_BOLT_URL / NEO4J_BOLT_USER / NEO4J_BOLT_PASSWORD).
"""

import json
import logging
import os
from datetime import datetime, timedelta

try:
    from airflow.decorators import dag, task
    from airflow.hooks.base import BaseHook
    from airflow.models import Variable
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _resolve_bolt_config() -> dict:
    """Resolve a config Bolt do Neo4j (Airflow Variable -> fallback env vars).

    A Variable "neo4j_bolt_url" guarda um JSON {"url","user","password"} (vem do secret
    airflow-variables-neo4j_bolt_url). Se ausente, monta a partir de env vars.
    """
    raw = Variable.get("neo4j_bolt_url", default_var=None)
    if raw:
        return raw if isinstance(raw, dict) else json.loads(raw)

    url = os.environ.get("NEO4J_BOLT_URL")
    if not url:
        raise ValueError(
            "Config Neo4j ausente: defina a Airflow Variable 'neo4j_bolt_url' "
            "(JSON com url/user/password) ou as env vars NEO4J_BOLT_URL/_USER/_PASSWORD."
        )
    return {
        "url": url,
        "user": os.environ.get("NEO4J_BOLT_USER", "neo4j"),
        "password": os.environ.get("NEO4J_BOLT_PASSWORD", ""),
    }


@dag(
    dag_id="sync_graph_to_neo4j",
    description="Sincroniza entity_registry + entity_edges (Postgres) para o Neo4j via MERGE idempotente",
    schedule="30 */6 * * *",  # 30min apos project_entity_graph (que roda 0 */6)
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "entities", "graph", "neo4j"],
    default_args={
        "owner": "data-platform",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
        "execution_timeout": timedelta(minutes=30),
    },
    doc_md="""
    ### Sync da projecao de grafo para o Neo4j (Fase 6b)

    Le `entity_registry` (nos) + `entity_edges` (arestas agregadas) do Postgres e faz
    `MERGE` idempotente no Neo4j (driver Bolt):

    - Nos: `(:Entity {entity_id, name, type, wikidata_id, agency_key})`.
    - Arestas: `[:CO_MENTIONED_WITH {weight, article_count, first_seen, last_seen}]`,
      `[:SUBORDINATE_TO]`, `[:IS_AGENCY]`.

    Roda apos `project_entity_graph`. Idempotente: re-rodar nao duplica nos/arestas.
    """,
)
def sync_graph_to_neo4j():
    @task
    def sync_to_neo4j(**context):
        """Le do Postgres e faz MERGE idempotente no Neo4j."""
        from data_platform.jobs.graph.neo4j_sync import sync_graph_to_neo4j as run_sync

        conn = BaseHook.get_connection("postgres_default")
        db_url = conn.get_uri().replace("postgres://", "postgresql://", 1)

        bolt_config = _resolve_bolt_config()

        result = run_sync(db_url, bolt_config)
        logger.info("Sync do grafo para Neo4j concluido: %s", result)
        return result

    sync_to_neo4j()


dag_instance = sync_graph_to_neo4j()
