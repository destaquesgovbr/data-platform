"""Projecao em grafo das entidades (Fase 6a): rebuild de news_entities e recompute de entity_edges.

Tudo set-based e idempotente. As funcoes deste modulo constroem os comandos SQL (sem interpolar
dados — apenas parametros via psycopg2) e executam contra o Postgres. A divisao em pequenas funcoes
de construcao de SQL permite testar a logica (threshold, ordem canonica, filtro de canonical_id nulo)
sem precisar de um banco real.

Fonte: news_features.features->'entities' (apenas mencoes com canonical_id NAO-NULL).
Saida: news_entities (mencao normalizada) -> entity_edges (co-mencao + estruturais)
-> entity_stats (por entidade) + entity_graph_meta (totais do corpus).
"""

import logging

from data_platform.jobs.graph.content_keys import MISSING_COLUMN_REASON, has_content_key_column

logger = logging.getLogger(__name__)

# Threshold de co-mencao: so arestas sustentadas por >= 2 artigos viram aresta.
# Descarta co-mencao de artigo unico (evita "hairball" / ruido).
CO_MENTION_MIN_WEIGHT = 2

# Tipos de aresta materializados.
KIND_CO_MENTION = "co_mention"
KIND_SUBORDINATE_TO = "subordinate_to"
KIND_IS_AGENCY = "is_agency"

# Chave de deduplicacao de conteudo: UNICO ponto que define quando dois artigos sao "o mesmo
# conteudo" para unique_content_count (arestas e entity_stats) e total_unique_content (meta).
# Contrato: exatamente 1 linha por artigo de news, colunas (unique_id, content_key).
# 1) news.content_key: unique_id do lider do grupo de quase-duplicatas (regra H5, migracao 035,
#    calculada por content_keys.compute_content_keys na task anterior da DAG); NULL = sem
#    quase-duplicata ou ainda nao calculada.
# 2) news.content_hash: 16 hex do SHA-256 de titulo + conteudo normalizados (009/010), que so
#    junta textos identicos.
# 3) o proprio artigo.
# Os espacos de chave nao colidem (unique_id do lider x 16 hex). A graphql-api usa a mesma regra
# em _CONTENT_DEDUP_KEY_SQL.
ARTICLE_CONTENT_KEY_SQL = """
    SELECT n.unique_id, COALESCE(n.content_key, n.content_hash, n.unique_id) AS content_key
    FROM news n
"""

# Sem news.content_key (codigo em producao antes da 035, ou 035 revertida): so o hash exato, como
# antes do DP-1b. O grafo nao depende da ordem entre o merge e a migracao.
ARTICLE_CONTENT_KEY_FALLBACK_SQL = """
    SELECT n.unique_id, COALESCE(n.content_hash, n.unique_id) AS content_key
    FROM news n
"""


def article_content_key_sql(conn) -> str:
    """ARTICLE_CONTENT_KEY_SQL se news.content_key existe; senao o fallback, com aviso."""
    if has_content_key_column(conn):
        return ARTICLE_CONTENT_KEY_SQL
    logger.warning(
        "grafo: %s; contando conteudos distintos pelo content_hash", MISSING_COLUMN_REASON
    )
    return ARTICLE_CONTENT_KEY_FALLBACK_SQL


def _with_content_key(sql: str, content_key_sql: str) -> str:
    """Troca o fragmento ARTICLE_CONTENT_KEY_SQL embutido em `sql` por `content_key_sql`."""
    return sql.replace(ARTICLE_CONTENT_KEY_SQL, content_key_sql)


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
#   unique_content_count = nº de conteudos distintos (content_key de ARTICLE_CONTENT_KEY_SQL):
#                   republicacoes da mesma materia por varios orgaos contam 1
#   first/last_seen = min/max(published_at)
# Threshold via HAVING: so pares com >= %(min_weight)s artigos — na contagem BRUTA, para o
# conjunto de arestas (portal/Neo4j) nao mudar com o dedup.
#
# Idempotente: DELETE da kind 'co_mention' + INSERT recomputado.
DELETE_CO_MENTION_EDGES_SQL = "DELETE FROM entity_edges WHERE kind = %(kind)s"

RECOMPUTE_CO_MENTION_EDGES_SQL = (
    """
    INSERT INTO entity_edges (src_id, dst_id, kind, weight, article_count,
                              unique_content_count, first_seen, last_seen)
    SELECT
        a.entity_id                       AS src_id,
        b.entity_id                       AS dst_id,
        %(kind)s                          AS kind,
        COUNT(DISTINCT a.unique_id)       AS weight,
        COUNT(DISTINCT a.unique_id)       AS article_count,
        COUNT(DISTINCT ck.content_key)    AS unique_content_count,
        MIN(a.published_at)               AS first_seen,
        MAX(a.published_at)               AS last_seen
    FROM news_entities a
    JOIN news_entities b
      ON a.unique_id = b.unique_id
     AND a.entity_id < b.entity_id
    -- 1 linha por artigo (FK news_entities -> news): o join nao descarta nem duplica mencoes
    JOIN ("""
    + ARTICLE_CONTENT_KEY_SQL
    + """) ck ON ck.unique_id = a.unique_id
    GROUP BY a.entity_id, b.entity_id
    HAVING COUNT(DISTINCT a.unique_id) >= %(min_weight)s
"""
)


def recompute_co_mention_edges(
    conn,
    min_weight: int = CO_MENTION_MIN_WEIGHT,
    content_key_sql: str = ARTICLE_CONTENT_KEY_SQL,
) -> int:
    """Recomputa as arestas kind='co_mention' (idempotente: DELETE da kind + INSERT).

    `content_key_sql`: chave de conteudo por artigo (ver article_content_key_sql).
    Retorna o numero de arestas inseridas.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(DELETE_CO_MENTION_EDGES_SQL, {"kind": KIND_CO_MENTION})
        cursor.execute(
            _with_content_key(RECOMPUTE_CO_MENTION_EDGES_SQL, content_key_sql),
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
# (d) Estatisticas por entidade e totais do corpus (lift/PMI na graphql-api)
# ---------------------------------------------------------------------------

# Remove as entidades que ficaram sem mencao no news_entities recem-reconstruido.
DELETE_STALE_ENTITY_STATS_SQL = """
    DELETE FROM entity_stats s
    WHERE NOT EXISTS (
        SELECT 1 FROM news_entities ne WHERE ne.entity_id = s.entity_id
    )
"""

# Por entidade: artigos distintos, conteudos distintos (content_key de ARTICLE_CONTENT_KEY_SQL,
# como em unique_content_count das arestas) e janela de mencoes. Upsert em vez de DELETE + INSERT para
# nao apagar a curadoria (is_generic/generic_reason, que este job nao calcula); sem TRUNCATE,
# os leitores seguem vendo o snapshot anterior ate o commit.
UPSERT_ENTITY_STATS_SQL = (
    """
    INSERT INTO entity_stats (entity_id, article_count, unique_content_count,
                              first_seen, last_seen, computed_at)
    SELECT
        ne.entity_id,
        COUNT(DISTINCT ne.unique_id)   AS article_count,
        COUNT(DISTINCT ck.content_key) AS unique_content_count,
        MIN(ne.published_at)           AS first_seen,
        MAX(ne.published_at)           AS last_seen,
        NOW()                          AS computed_at
    FROM news_entities ne
    JOIN ("""
    + ARTICLE_CONTENT_KEY_SQL
    + """) ck ON ck.unique_id = ne.unique_id
    GROUP BY ne.entity_id
    ON CONFLICT (entity_id) DO UPDATE SET
        article_count        = EXCLUDED.article_count,
        unique_content_count = EXCLUDED.unique_content_count,
        first_seen           = EXCLUDED.first_seen,
        last_seen            = EXCLUDED.last_seen,
        computed_at          = EXCLUDED.computed_at
"""
)

# Totais do corpus do grafo (linha unica id = 1). Universo = artigos com ao menos uma mencao
# canonica em news_entities (o mesmo das contagens por entidade/aresta), nao a tabela news
# inteira: e o denominador do lift/PMI. Agregado sem GROUP BY: corpus vazio grava (0, 0).
UPSERT_ENTITY_GRAPH_META_SQL = (
    """
    INSERT INTO entity_graph_meta (id, total_articles, total_unique_content, computed_at)
    SELECT
        1,
        COUNT(DISTINCT ne.unique_id),
        COUNT(DISTINCT ck.content_key),
        NOW()
    FROM news_entities ne
    JOIN ("""
    + ARTICLE_CONTENT_KEY_SQL
    + """) ck ON ck.unique_id = ne.unique_id
    ON CONFLICT (id) DO UPDATE SET
        total_articles       = EXCLUDED.total_articles,
        total_unique_content = EXCLUDED.total_unique_content,
        computed_at          = EXCLUDED.computed_at
    RETURNING total_articles, total_unique_content
"""
)


def recompute_entity_stats(conn, content_key_sql: str = ARTICLE_CONTENT_KEY_SQL) -> dict:
    """Recomputa entity_stats e entity_graph_meta a partir de news_entities.

    Roda depois do rebuild de news_entities, na mesma transacao. `content_key_sql`: chave de
    conteudo por artigo (ver article_content_key_sql). Retorna as contagens.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(DELETE_STALE_ENTITY_STATS_SQL)
        stale_removed = cursor.rowcount
        cursor.execute(_with_content_key(UPSERT_ENTITY_STATS_SQL, content_key_sql))
        entity_stats = cursor.rowcount
        cursor.execute(_with_content_key(UPSERT_ENTITY_GRAPH_META_SQL, content_key_sql))
        total_articles, total_unique_content = cursor.fetchone()
        logger.info(
            "entity_stats recomputadas: %s entidades (%s removidas); corpus: %s artigos, "
            "%s conteudos distintos",
            entity_stats,
            stale_removed,
            total_articles,
            total_unique_content,
        )
        return {
            "stale_removed": stale_removed,
            "entity_stats": entity_stats,
            "total_articles": total_articles,
            "total_unique_content": total_unique_content,
        }
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Orquestracao (uma transacao para todo o rebuild)
# ---------------------------------------------------------------------------


def project_entity_graph(db_url: str, min_weight: int = CO_MENTION_MIN_WEIGHT) -> dict:
    """Executa o rebuild completo (news_entities + entity_edges + entity_stats) numa transacao.

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
        content_key_sql = article_content_key_sql(conn)
        mentions = rebuild_news_entities(conn)
        co_mention = recompute_co_mention_edges(
            conn, min_weight=min_weight, content_key_sql=content_key_sql
        )
        structural = recompute_structural_edges(conn)
        stats = recompute_entity_stats(conn, content_key_sql=content_key_sql)
        conn.commit()
        return {
            "status": "ok",
            "news_entities": mentions,
            "co_mention_edges": co_mention,
            "subordinate_to_edges": structural["subordinate_to"],
            "is_agency_edges": structural["is_agency"],
            "entity_stats": stats["entity_stats"],
            "total_articles": stats["total_articles"],
            "total_unique_content": stats["total_unique_content"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
