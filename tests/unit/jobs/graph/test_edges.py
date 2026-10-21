"""Testes da projecao em grafo de entidades (Fase 6a) — jobs/graph/edges.py.

Sem banco real: validamos os invariantes do SQL (threshold, ordem canonica, filtro de
canonical_id nulo) e a orquestracao das funcoes via um cursor mockado.
"""

import inspect
import re
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.graph import edges
from data_platform.jobs.graph.edges import (
    ARTICLE_CONTENT_KEY_SQL,
    CO_MENTION_MIN_WEIGHT,
    DELETE_CO_MENTION_EDGES_SQL,
    DELETE_STALE_ENTITY_STATS_SQL,
    KIND_CO_MENTION,
    KIND_IS_AGENCY,
    KIND_SUBORDINATE_TO,
    REBUILD_NEWS_ENTITIES_SQL,
    RECOMPUTE_CO_MENTION_EDGES_SQL,
    UPSERT_ENTITY_GRAPH_META_SQL,
    UPSERT_ENTITY_STATS_SQL,
    project_entity_graph,
    rebuild_news_entities,
    recompute_co_mention_edges,
    recompute_entity_stats,
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

    def test_unique_content_count_conta_chaves_de_conteudo_distintas(self):
        """Artigos com a mesma content_key (republicacao) contam 1."""
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert (
            f"join ({_normalize(ARTICLE_CONTENT_KEY_SQL)}) ck on ck.unique_id = a.unique_id" in norm
        )
        assert "count(distinct ck.content_key) as unique_content_count" in norm

    def test_insert_lista_unique_content_count(self):
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        assert (
            "insert into entity_edges (src_id, dst_id, kind, weight, article_count, "
            "unique_content_count, first_seen, last_seen)" in norm
        )

    def test_threshold_segue_na_contagem_bruta(self):
        """O conjunto de arestas nao muda (portal/Neo4j): HAVING so na contagem bruta."""
        norm = _normalize(RECOMPUTE_CO_MENTION_EDGES_SQL)
        having = norm.split(" having ", 1)[1]
        assert "content_key" not in having
        assert "unique_content_count" not in having


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
# Chave de deduplicacao de conteudo: um unico ponto a trocar
# ---------------------------------------------------------------------------
class TestArticleContentKey:
    def test_uma_linha_por_artigo_de_news(self):
        norm = _normalize(ARTICLE_CONTENT_KEY_SQL)
        assert norm.startswith("select n.unique_id,")
        assert norm.endswith("as content_key from news n")

    def test_hoje_e_o_content_hash_ou_o_proprio_artigo(self):
        norm = _normalize(ARTICLE_CONTENT_KEY_SQL)
        assert "coalesce(n.content_hash, n.unique_id) as content_key" in norm

    def test_regra_de_dedup_definida_num_lugar_so(self):
        """Arestas, entity_stats e meta usam o mesmo fragmento; content_hash so aparece nele."""
        for sql in (
            RECOMPUTE_CO_MENTION_EDGES_SQL,
            UPSERT_ENTITY_STATS_SQL,
            UPSERT_ENTITY_GRAPH_META_SQL,
        ):
            assert ARTICLE_CONTENT_KEY_SQL in sql
        code = inspect.getsource(edges)
        assert code.count("content_hash, n.unique_id") == 1


# ---------------------------------------------------------------------------
# Invariantes do SQL de entity_stats / entity_graph_meta
# ---------------------------------------------------------------------------
class TestEntityStatsSQLInvariants:
    def test_article_count_e_unique_content_count_por_entidade(self):
        norm = _normalize(UPSERT_ENTITY_STATS_SQL)
        assert (
            f"from news_entities ne join ({_normalize(ARTICLE_CONTENT_KEY_SQL)}) ck "
            "on ck.unique_id = ne.unique_id" in norm
        )
        assert "count(distinct ne.unique_id) as article_count" in norm
        assert "count(distinct ck.content_key) as unique_content_count" in norm
        assert "group by ne.entity_id" in norm

    def test_first_last_seen_sao_min_max_published_at(self):
        norm = _normalize(UPSERT_ENTITY_STATS_SQL)
        assert "min(ne.published_at) as first_seen" in norm
        assert "max(ne.published_at) as last_seen" in norm

    def test_upsert_atualiza_contagens_e_computed_at(self):
        norm = _normalize(UPSERT_ENTITY_STATS_SQL)
        update = norm.split("on conflict (entity_id) do update set", 1)[1]
        for col in (
            "article_count",
            "unique_content_count",
            "first_seen",
            "last_seen",
            "computed_at",
        ):
            assert f"{col} = excluded.{col}" in update

    def test_preserva_curadoria_is_generic(self):
        """is_generic/generic_reason sao curadoria: o rebuild nao grava nem sobrescreve."""
        norm = _normalize(UPSERT_ENTITY_STATS_SQL)
        assert "is_generic" not in norm
        assert "generic_reason" not in norm

    def test_remove_entidades_sem_mencao(self):
        norm = _normalize(DELETE_STALE_ENTITY_STATS_SQL)
        assert norm.startswith("delete from entity_stats s where not exists (")
        assert "from news_entities ne where ne.entity_id = s.entity_id" in norm

    def test_meta_e_linha_unica_com_totais_do_corpus_com_mencao(self):
        norm = _normalize(UPSERT_ENTITY_GRAPH_META_SQL)
        assert "insert into entity_graph_meta (id, total_articles, total_unique_content" in norm
        assert "count(distinct ne.unique_id)" in norm
        assert "count(distinct ck.content_key)" in norm
        assert (
            f"from news_entities ne join ({_normalize(ARTICLE_CONTENT_KEY_SQL)}) ck "
            "on ck.unique_id = ne.unique_id" in norm
        )
        assert "on conflict (id) do update set" in norm
        assert "returning total_articles, total_unique_content" in norm

    def test_sem_truncate_leitores_mantem_snapshot_anterior(self):
        for sql in (
            UPSERT_ENTITY_STATS_SQL,
            DELETE_STALE_ENTITY_STATS_SQL,
            UPSERT_ENTITY_GRAPH_META_SQL,
        ):
            assert "truncate" not in sql.lower()

    def test_sql_nao_usa_fstring_interpolando_dados(self):
        for sql in (
            UPSERT_ENTITY_STATS_SQL,
            DELETE_STALE_ENTITY_STATS_SQL,
            UPSERT_ENTITY_GRAPH_META_SQL,
        ):
            assert "{" not in sql
            assert "}" not in sql


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


class TestRecomputeEntityStatsExecution:
    def test_remove_obsoletas_depois_upsert_stats_e_meta(self):
        conn, cursor = _conn_with_cursor(rowcount=5)
        cursor.fetchone.return_value = (120, 95)

        result = recompute_entity_stats(conn)

        executed = [c.args[0] for c in cursor.execute.call_args_list]
        assert executed == [
            DELETE_STALE_ENTITY_STATS_SQL,
            UPSERT_ENTITY_STATS_SQL,
            UPSERT_ENTITY_GRAPH_META_SQL,
        ]
        assert result == {
            "stale_removed": 5,
            "entity_stats": 5,
            "total_articles": 120,
            "total_unique_content": 95,
        }
        cursor.close.assert_called_once()


class TestProjectEntityGraphTransaction:
    def test_estatisticas_na_mesma_transacao_das_arestas(self):
        """entity_stats/meta recomputadas antes do unico commit (snapshot coerente com as arestas)."""
        conn = MagicMock()
        calls = MagicMock()
        conn.commit.side_effect = lambda: calls.commit()
        with (
            patch("psycopg2.connect", return_value=conn),
            patch.object(edges, "rebuild_news_entities", calls.rebuild) as rebuild,
            patch.object(edges, "recompute_co_mention_edges", calls.co_mention) as co_mention,
            patch.object(edges, "recompute_structural_edges", calls.structural) as structural,
            patch.object(edges, "recompute_entity_stats", calls.stats) as stats,
        ):
            rebuild.return_value = 10
            co_mention.return_value = 4
            structural.return_value = {"subordinate_to": 2, "is_agency": 1}
            stats.return_value = {
                "stale_removed": 0,
                "entity_stats": 7,
                "total_articles": 6,
                "total_unique_content": 5,
            }

            result = project_entity_graph("postgresql://fake")

        order = [name for name, _, _ in calls.mock_calls]
        assert order == ["rebuild", "co_mention", "structural", "stats", "commit"]
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        assert result["entity_stats"] == 7
        assert result["total_articles"] == 6
        assert result["total_unique_content"] == 5
        assert result["co_mention_edges"] == 4

    def test_falha_nas_estatisticas_faz_rollback_de_tudo(self):
        conn = MagicMock()
        with (
            patch("psycopg2.connect", return_value=conn),
            patch.object(edges, "rebuild_news_entities", return_value=1),
            patch.object(edges, "recompute_co_mention_edges", return_value=1),
            patch.object(
                edges,
                "recompute_structural_edges",
                return_value={"subordinate_to": 0, "is_agency": 0},
            ),
            patch.object(edges, "recompute_entity_stats", side_effect=RuntimeError("boom")),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                project_entity_graph("postgresql://fake")

        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
