"""Sync da projecao de grafo de entidades para o Neo4j (Fase 6b).

Le os nos (entity_registry) e as arestas agregadas (entity_edges) do Postgres e faz
MERGE idempotente no Neo4j via driver Bolt. 1o corte: so nos :Entity + arestas
agregadas (sem nos :Article — o grafo fica compacto, milhares de nos).

Idempotente: usa MERGE por chave estavel (entity_id nos nos; par + tipo nas arestas),
entao re-rodar nao duplica. As arestas estruturais sao direcionadas (subordinate_to /
is_agency); co_mention e nao-direcionada mas armazenada com ordem canonica src < dst
no Postgres, refletida aqui como uma unica aresta CO_MENTIONED_WITH por par.

Conexao Neo4j: dict {"url","user","password"} vindo da Airflow Variable "neo4j_bolt_url"
(Secret Manager backend) com fallback para env vars (NEO4J_BOLT_URL/_USER/_PASSWORD).
"""

import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Mapeia o `kind` em entity_edges para o tipo de relacionamento no Neo4j.
EDGE_KIND_TO_REL = {
    "co_mention": "CO_MENTIONED_WITH",
    "subordinate_to": "SUBORDINATE_TO",
    "is_agency": "IS_AGENCY",
}

# Tamanho de lote para o UNWIND (evita transacoes gigantes / estouro de memoria).
BATCH_SIZE = 1000

# --- Leitura do Postgres -----------------------------------------------------

SELECT_NODES_SQL = """
    SELECT
        entity_id,
        canonical_name AS name,
        type,
        wikidata_id,
        agency_key
    FROM entity_registry
"""

SELECT_EDGES_SQL = """
    SELECT
        src_id,
        dst_id,
        kind,
        weight,
        article_count,
        first_seen,
        last_seen
    FROM entity_edges
"""


def fetch_nodes(db_url: str) -> list[dict]:
    """Le todos os nos (entity_registry) do Postgres."""
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(SELECT_NODES_SQL)).mappings().all()
            return [dict(r) for r in rows]
    finally:
        engine.dispose()


def fetch_edges(db_url: str) -> list[dict]:
    """Le todas as arestas agregadas (entity_edges) do Postgres."""
    engine = create_engine(db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(SELECT_EDGES_SQL)).mappings().all()
            edges: list[dict] = []
            for r in rows:
                edge = dict(r)
                # Datas como ISO string (o driver Neo4j aceita string; mantemos simples
                # e deterministico no MERGE de propriedades).
                for k in ("first_seen", "last_seen"):
                    if edge.get(k) is not None:
                        edge[k] = edge[k].isoformat()
                edges.append(edge)
            return edges
    finally:
        engine.dispose()


# --- Cypher (MERGE idempotente) ---------------------------------------------

# Nos: MERGE por entity_id (chave estavel) + SET das propriedades.
MERGE_NODES_CYPHER = """
    UNWIND $rows AS row
    MERGE (e:Entity {entity_id: row.entity_id})
    SET e.name = row.name,
        e.type = row.type,
        e.wikidata_id = row.wikidata_id,
        e.agency_key = row.agency_key
"""

# Arestas: o tipo de relacionamento e fixo por chamada (nao da pra parametrizar o label
# do relacionamento no Cypher), entao agrupamos por rel_type e usamos um template.
# MERGE pelo par (src, dst) garante idempotencia; SET atualiza os pesos a cada sync.
_MERGE_EDGES_CYPHER_TMPL = """
    UNWIND $rows AS row
    MATCH (src:Entity {{entity_id: row.src_id}})
    MATCH (dst:Entity {{entity_id: row.dst_id}})
    MERGE (src)-[r:{rel_type}]->(dst)
    SET r.weight = row.weight,
        r.article_count = row.article_count,
        r.first_seen = row.first_seen,
        r.last_seen = row.last_seen
"""


def _chunked(items: list, size: int):
    """Divide uma lista em lotes de tamanho `size`."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _resolve_neo4j_config(bolt_config: dict) -> tuple[str, str, str]:
    """Extrai (url, user, password) do dict de configuracao, com defaults seguros."""
    url = bolt_config.get("url") or bolt_config.get("uri")
    user = bolt_config.get("user", "neo4j")
    password = bolt_config.get("password")
    if not url or not password:
        raise ValueError(
            "Configuracao Neo4j incompleta: 'url' e 'password' sao obrigatorios "
            "(recebido: chaves=%s)" % sorted(bolt_config.keys())
        )
    return url, user, password


def parse_bolt_config(raw: str | dict) -> dict:
    """Normaliza a config Bolt (aceita JSON string ou dict)."""
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


def sync_graph_to_neo4j(db_url: str, bolt_config: dict) -> dict:
    """Sincroniza nos + arestas do Postgres para o Neo4j (MERGE idempotente).

    Args:
        db_url: connection string do Postgres (postgresql://...).
        bolt_config: dict {"url","user","password"} de conexao Bolt.

    Returns:
        dict com contagem de nos/arestas sincronizados por tipo.
    """
    # Import local: o driver so existe no ambiente do Composer (pypi_packages),
    # nao no import-time dos testes / parsing de DAG.
    from neo4j import GraphDatabase

    url, user, password = _resolve_neo4j_config(bolt_config)

    nodes = fetch_nodes(db_url)
    edges = fetch_edges(db_url)
    logger.info("Lidos do Postgres: %d nos, %d arestas", len(nodes), len(edges))

    # Agrupa arestas por tipo de relacionamento (label nao e parametrizavel no Cypher).
    edges_by_rel: dict[str, list[dict]] = {}
    for edge in edges:
        rel_type = EDGE_KIND_TO_REL.get(edge["kind"])
        if rel_type is None:
            logger.warning("Ignorando aresta de kind desconhecido: %s", edge["kind"])
            continue
        edges_by_rel.setdefault(rel_type, []).append(edge)

    result = {"nodes": 0, "edges": {}}
    driver = GraphDatabase.driver(url, auth=(user, password))
    try:
        with driver.session() as session:
            # Constraint de unicidade (idempotente) garante MERGE rapido por entity_id.
            session.run(
                "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE"
            )

            # Nos primeiro (as arestas dependem deles via MATCH).
            for batch in _chunked(nodes, BATCH_SIZE):
                session.run(MERGE_NODES_CYPHER, rows=batch)
                result["nodes"] += len(batch)

            # Arestas, por tipo de relacionamento.
            for rel_type, rel_edges in edges_by_rel.items():
                cypher = _MERGE_EDGES_CYPHER_TMPL.format(rel_type=rel_type)
                count = 0
                for batch in _chunked(rel_edges, BATCH_SIZE):
                    session.run(cypher, rows=batch)
                    count += len(batch)
                result["edges"][rel_type] = count
    finally:
        driver.close()

    logger.info("Sync Neo4j concluido: %s", result)
    return result
