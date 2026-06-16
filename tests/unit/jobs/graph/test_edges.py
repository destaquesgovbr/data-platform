"""Testes da projecao em grafo de entidades (Fase 6a) — jobs/graph/edges.py.

Sem banco real: validamos os invariantes do SQL (threshold, ordem canonica, filtro de
canonical_id nulo) e a orquestracao das funcoes via um cursor mockado.
"""

import re
from unittest.mock import MagicMock

from data_platform.jobs.graph.edges import (
    CO_MENTION_MIN_WEIGHT,
    DELETE_CO_MENTION_EDGES_SQL,
    KIND_CO_MENTION,
    KIND_IS_AGENCY,
    KIND_SUBORDINATE_TO,
    REBUILD_NEWS_ENTITIES_SQL,
    RECOMPUTE_CO_MENTION_EDGES_SQL,
    rebuild_news_entities,
    recompute_co_mention_edges,
    recompute_structural_edges,
)


def _normalize(sql: str) -> str:
    """Colapsa espacos para facilitar asserts de substring."""
    return re.sub(r"\s+", " ", sql).strip().lower()


# ---------------------------------------------------------------------------
# Invariantes do SQL de co-mencao
# ---------------------------------------------------------------------------
class TestCoMentionSQLInvariants:
    def test_respeita_ordem_canonica_src_menor_dst(self):
        """O self-join deve usar a.entity_id < b.entity_id (par nao-direcionado, sem duplicar)."""
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert "a.entity_id < b.entity_id" in norm
        # nao deve usar != (que duplicaria (A,B) e (B,A))
        assert "a.entity_id != b.entity_id" not in norm
        assert "a.entity_id <> b.entity_id" not in norm

    def test_join_no_mesmo_unique_id(self):
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert "a.unique_id = b.unique_id" in norm

    def test_aplica_threshold_via_having_parametrizado(self):
        """O threshold deve ser HAVING count(distinct ...) >= %(min_weight)s (parametrizado)."""
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert "having count(distinct a.unique_id) >= %(min_weight)s" in norm

    def test_weight_e_count_distinct_de_artigos(self):
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert "count(distinct a.unique_id) as weight" in norm
        assert "count(distinct a.unique_id) as article_count" in norm

    def test_first_last_seen_sao_min_max_published_at(self):
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert "min(a.published_at) as first_seen" in norm
        assert "max(a.published_at) as last_seen" in norm

    def test_threshold_default_e_dois(self):
        assert CO_MENTION_MIN_WEIGHT == 2

    def test_sql_nao_usa_fstring_interpolando_dados(self):
        """Garantia anti-injection: o SQL so usa placeholders psycopg2 (%(...)s), nada de {}."""
        assert "{" not in RECOMPUTE_CO_MENTION_EDGES_SQL
        assert "}" not in RECOMPUTE_CO_MENTION_EDGES_SQL


# ---------------------------------------------------------------------------
# Invariantes do SQL de rebuild de news_entities
# ---------------------------------------------------------------------------
class TestRebuildNewsEntitiesSQLInvariants:
    def test_ignora_canonical_id_nulo(self):
        """So mencoes com canonical_id NAO-NULL entram em news_entities."""
        norm = _normalize(REBUILD_NEWS_ENTITIES_SQL)
        assert "ent->>'canonical_id' is not null" in norm

    def test_expande_entities_com_jsonb_array_elements(self):
        norm = _normalize(REBUILD_NEWS_ENTITIES_SQL)
        assert "jsonb_array_elements(" in norm
        assert "nf.features->'entities'" in norm

    def test_join_news_para_published_at(self):
        norm = _normalize(REBUILD_NEWS_ENTITIES_SQL)
        assert "join news n on n.unique_id = nf.unique_id" in norm
        assert "n.published_at" in norm

    def test_valida_canonical_id_existe_no_registry(self):
        """Evita violar a FK em dados parciais: o canonical_id deve existir em entity_registry."""
        norm = _normalize(REBUILD_NEWS_ENTITIES_SQL)
        assert "exists (" in norm
        assert "from entity_registry er" in norm

    def test_agrega_por_artigo_e_entidade(self):
        norm = _normalize(REBUILD_NEWS_ENTITIES_SQL)
        assert "group by nf.unique_id, ent->>'canonical_id', n.published_at" in norm


# ---------------------------------------------------------------------------
# Orquestracao via cursor mockado
# ---------------------------------------------------------------------------
def _conn_with_cursor(rowcount: int = 0):
    cursor = MagicMock()
    cursor.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestRebuildNewsEntitiesExecution:
    def test_truncate_antes_de_insert(self):
        conn, cursor = _conn_with_cursor(rowcount=42)
        result = rebuild_news_entities(conn)

        assert result == 42
        # primeira chamada = TRUNCATE, segunda = INSERT
        first_sql = cursor.execute.call_args_list[0].args[0]
        second_sql = cursor.execute.call_args_list[1].args[0]
        assert "truncate" in first_sql.lower()
        assert "insert into news_entities" in _normalize(second_sql)
        cursor.close.assert_called_once()


class TestRecomputeCoMentionExecution:
    def test_delete_kind_depois_insert_com_threshold(self):
        conn, cursor = _conn_with_cursor(rowcount=7)
        result = recompute_co_mention_edges(conn, min_weight=2)

        assert result == 7
        # 1ª chamada: DELETE da kind co_mention
        del_call = cursor.execute.call_args_list[0]
        assert del_call.args[0] == DELETE_CO_MENTION_EDGES_SQL
        assert del_call.args[1] == {"kind": KIND_CO_MENTION}
        # 2ª chamada: INSERT com kind + min_weight parametrizados
        ins_call = cursor.execute.call_args_list[1]
        assert ins_call.args[1] == {"kind": KIND_CO_MENTION, "min_weight": 2}

    def test_threshold_default_propaga(self):
        conn, cursor = _conn_with_cursor(rowcount=0)
        recompute_co_mention_edges(conn)
        ins_call = cursor.execute.call_args_list[1]
        assert ins_call.args[1]["min_weight"] == CO_MENTION_MIN_WEIGHT


class TestRecomputeStructuralExecution:
    def test_delete_e_insert_por_kind(self):
        conn, cursor = _conn_with_cursor(rowcount=3)
        result = recompute_structural_edges(conn)

        executed = [c.args for c in cursor.execute.call_args_list]
        # deletes por kind subordinate_to e is_agency presentes
        deletes = [a for a in executed if a[0] == DELETE_CO_MENTION_EDGES_SQL]
        deleted_kinds = {a[1]["kind"] for a in deletes}
        assert deleted_kinds == {KIND_SUBORDINATE_TO, KIND_IS_AGENCY}

        # resultado agrega contagens (rowcount=3 por insert; 2 inserts subordinate + 1 is_agency)
        assert result["subordinate_to"] == 6
        assert result["is_agency"] == 3
