"""Projecao em grafo das entidades (Fase 6a): rebuild de news_entities e recompute de entity_edges.

Tudo set-based e idempotente. As funcoes deste modulo constroem os comandos SQL (sem interpolar
dados — apenas parametros via psycopg2) e executam contra o Postgres. A divisao em pequenas funcoes
de construcao de SQL permite testar a logica (threshold, ordem canonica, filtro de canonical_id nulo)
sem precisar de um banco real.

Fonte: news_features.features->'entities' (apenas mencoes com canonical_id NAO-NULL).
Saida: news_entities (mencao normalizada) -> entity_edges (co-mencao + estruturais).
"""

import logging

logger = logging.getLogger(__name__)

# Threshold de co-mencao: so arestas sustentadas por >= 2 artigos viram aresta.
# Descarta co-mencao de artigo unico (evita "hairball" / ruido).
CO_MENTION_MIN_WEIGHT = 2

# Tipos de aresta materializados.
KIND_CO_MENTION = "co_mention"
KIND_SUBORDINATE_TO = "subordinate_to"
KIND_IS_AGENCY = "is_agency"


# ---------------------------------------------------------------------------
# (a) Rebuild de news_entities a partir de news_features
# ---------------------------------------------------------------------------

# Expande features->'entities' (JSONB array) em linhas, mantendo apenas mencoes com
# canonical_id NAO-NULL (so essas contam para o grafo). Faz join com news para desnormalizar
# published_at. Agrega por (unique_id, entity_id) — o mesmo canonical_id pode aparecer em varias
# mencoes do array (formas de superficie distintas) e precisa colapsar para a PK.
#
# Idempotente: TRUNCATE + INSERT reconstroi a tabela inteira a cada run (rebuild barato).
TRUNCATE_NEWS_ENTITIES_SQL = "TRUNCATE TABLE news_entities"

REBUILD_NEWS_ENTITIES_SQL = """
    INSERT INTO news_entities (unique_id, entity_id, type, count, salience, published_at)
    SELECT
        nf.unique_id,
        ent->>'canonical_id'                              AS entity_id,
        MAX(ent->>'type')                                 AS type,
        SUM(COALESCE((ent->>'count')::int, 1))            AS count,
        MAX((ent->>'salience')::real)                     AS salience,
        n.published_at                                    AS published_at
    FROM news_features nf
    JOIN news n ON n.unique_id = nf.unique_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(nf.features->'entities', '[]'::jsonb)
    ) AS ent
    WHERE ent->>'canonical_id' IS NOT NULL
      -- garante que o canonical_id existe no registry (evita violar a FK em dados parciais)
      AND EXISTS (
          SELECT 1 FROM entity_registry er
          WHERE er.entity_id = ent->>'canonical_id'
      )
    GROUP BY nf.unique_id, ent->>'canonical_id', n.published_at
"""


def rebuild_news_entities(conn) -> int:
    """Reconstroi news_entities a partir de news_features (idempotente: TRUNCATE + INSERT).

    Retorna o numero de linhas (mencoes normalizadas) inseridas.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(TRUNCATE_NEWS_ENTITIES_SQL)
        cursor.execute(REBUILD_NEWS_ENTITIES_SQL)
        inserted = cursor.rowcount
        logger.info("news_entities reconstruida: %s mencoes normalizadas", inserted)
        return inserted
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# (b) Recompute de arestas de co-mencao
# ---------------------------------------------------------------------------

# Self-join de news_entities no mesmo unique_id com a.entity_id < b.entity_id (ordem canonica,
# aresta nao-direcionada sem duplicar par). Agrega por par:
#   weight        = nº de artigos distintos em co-mencao
#   article_count = idem (mesma metrica neste 1º corte)
#   first/last_seen = min/max(published_at)
# Threshold via HAVING: so pares com >= %(min_weight)s artigos.
#
# Idempotente: DELETE da kind 'co_mention' + INSERT recomputado.
DELETE_CO_MENTION_EDGES_SQL = "DELETE FROM entity_edges WHERE kind = %(kind)s"

RECOMPUTE_CO_MENTION_EDGES_SQL = """
    INSERT INTO entity_edges (src_id, dst_id, kind, weight, article_count, first_seen, last_seen)
    SELECT
        a.entity_id                       AS src_id,
        b.entity_id                       AS dst_id,
        %(kind)s                          AS kind,
        COUNT(DISTINCT a.unique_id)       AS weight,
        COUNT(DISTINCT a.unique_id)       AS article_count,
        MIN(a.published_at)               AS first_seen,
        MAX(a.published_at)               AS last_seen
    FROM news_entities a
    JOIN news_entities b
      ON a.unique_id = b.unique_id
     AND a.entity_id < b.entity_id
    GROUP BY a.entity_id, b.entity_id
    HAVING COUNT(DISTINCT a.unique_id) >= %(min_weight)s
"""


def recompute_co_mention_edges(conn, min_weight: int = CO_MENTION_MIN_WEIGHT) -> int:
    """Recomputa as arestas kind='co_mention' (idempotente: DELETE da kind + INSERT).

    Retorna o numero de arestas inseridas.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(DELETE_CO_MENTION_EDGES_SQL, {"kind": KIND_CO_MENTION})
        cursor.execute(
            RECOMPUTE_CO_MENTION_EDGES_SQL,
            {"kind": KIND_CO_MENTION, "min_weight": min_weight},
        )
        inserted = cursor.rowcount
        logger.info(
            "entity_edges[co_mention] recomputadas: %s arestas (weight >= %s)", inserted, min_weight
        )
        return inserted
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# (c) Recompute de arestas estruturais (deterministicas, sem LLM)
# ---------------------------------------------------------------------------

# subordinate_to via agencies.parent_key: liga a entity_id da agencia filha a entity_id da agencia
# pai, resolvendo cada agency.key para entity_registry.agency_key. Direcionada (src = filho, dst = pai).
RECOMPUTE_SUBORDINATE_FROM_AGENCIES_SQL = """
    INSERT INTO entity_edges (src_id, dst_id, kind, weight, article_count, first_seen, last_seen)
    SELECT DISTINCT
        child_er.entity_id  AS src_id,
        parent_er.entity_id AS dst_id,
        %(kind)s            AS kind,
        0, 0, NULL::timestamptz, NULL::timestamptz
    FROM agencies child_ag
    JOIN agencies parent_ag        ON parent_ag.key = child_ag.parent_key
    JOIN entity_registry child_er  ON child_er.agency_key = child_ag.key
    JOIN entity_registry parent_er ON parent_er.agency_key = parent_ag.key
    WHERE child_ag.parent_key IS NOT NULL
      AND child_er.entity_id <> parent_er.entity_id
"""

# subordinate_to via entity_registry.extra->>'parent_qid': liga a entidade ao seu pai Wikidata,
# quando o QID pai existe no registry. Direcionada (src = filho, dst = pai).
RECOMPUTE_SUBORDINATE_FROM_PARENT_QID_SQL = """
    INSERT INTO entity_edges (src_id, dst_id, kind, weight, article_count, first_seen, last_seen)
    SELECT DISTINCT
        child.entity_id  AS src_id,
        parent.entity_id AS dst_id,
        %(kind)s         AS kind,
        0, 0, NULL::timestamptz, NULL::timestamptz
    FROM entity_registry child
    JOIN entity_registry parent ON parent.entity_id = child.extra->>'parent_qid'
    WHERE child.extra->>'parent_qid' IS NOT NULL
      AND child.entity_id <> parent.entity_id
    ON CONFLICT (src_id, dst_id, kind) DO NOTHING
"""

# is_agency: liga uma entidade ORG (com agency_key) a propria agencia, quando a agencia tambem
# tem um no proprio no registry. Direcionada (src = ORG, dst = agencia). Evita auto-loop.
RECOMPUTE_IS_AGENCY_SQL = """
    INSERT INTO entity_edges (src_id, dst_id, kind, weight, article_count, first_seen, last_seen)
    SELECT DISTINCT
        org.entity_id    AS src_id,
        agency.entity_id AS dst_id,
        %(kind)s         AS kind,
        0, 0, NULL::timestamptz, NULL::timestamptz
    FROM entity_registry org
    JOIN entity_registry agency
      ON agency.agency_key = org.agency_key
     AND agency.provenance = 'agencies_seed'
    WHERE org.type = 'ORG'
      AND org.agency_key IS NOT NULL
      AND org.entity_id <> agency.entity_id
    ON CONFLICT (src_id, dst_id, kind) DO NOTHING
"""


def recompute_structural_edges(conn) -> dict:
    """Recomputa as arestas estruturais (subordinate_to, is_agency).

    Idempotente: DELETE por kind + INSERT. Retorna contagem por kind.
    """
    cursor = conn.cursor()
    try:
        # subordinate_to: limpa a kind e reinsere das duas fontes (agencies + parent_qid)
        cursor.execute(DELETE_CO_MENTION_EDGES_SQL, {"kind": KIND_SUBORDINATE_TO})
        cursor.execute(RECOMPUTE_SUBORDINATE_FROM_AGENCIES_SQL, {"kind": KIND_SUBORDINATE_TO})
        sub_count = cursor.rowcount
        cursor.execute(RECOMPUTE_SUBORDINATE_FROM_PARENT_QID_SQL, {"kind": KIND_SUBORDINATE_TO})
        sub_count += cursor.rowcount

        # is_agency
        cursor.execute(DELETE_CO_MENTION_EDGES_SQL, {"kind": KIND_IS_AGENCY})
        cursor.execute(RECOMPUTE_IS_AGENCY_SQL, {"kind": KIND_IS_AGENCY})
        agency_count = cursor.rowcount

        logger.info(
            "entity_edges estruturais recomputadas: subordinate_to=%s, is_agency=%s",
            sub_count,
            agency_count,
        )
        return {"subordinate_to": sub_count, "is_agency": agency_count}
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Orquestracao (uma transacao para todo o rebuild)
# ---------------------------------------------------------------------------


def project_entity_graph(db_url: str, min_weight: int = CO_MENTION_MIN_WEIGHT) -> dict:
    """Executa o rebuild completo (news_entities + entity_edges) numa unica transacao.

    Args:
        db_url: connection string do Postgres.
        min_weight: threshold de co-mencao (default CO_MENTION_MIN_WEIGHT).

    Returns:
        dict com as contagens de cada etapa.
    """
    import psycopg2

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        mentions = rebuild_news_entities(conn)
        co_mention = recompute_co_mention_edges(conn, min_weight=min_weight)
        structural = recompute_structural_edges(conn)
        conn.commit()
        return {
            "status": "ok",
            "news_entities": mentions,
            "co_mention_edges": co_mention,
            "subordinate_to_edges": structural["subordinate_to"],
            "is_agency_edges": structural["is_agency"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
