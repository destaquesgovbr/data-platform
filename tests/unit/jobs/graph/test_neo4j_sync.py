"""Testes do sync da projecao de grafo para o Neo4j (Fase 6b) — jobs/graph/neo4j_sync.py.

Sem banco/Neo4j real: validamos os invariantes do Cypher (MERGE idempotente por chave
estavel), o mapeamento kind->relacionamento, o batching e a resolucao de config. A
orquestracao e testada com driver/session/engine mockados — o driver `neo4j` so existe
no ambiente do Composer e e importado lazily dentro da funcao.
"""

import re
import sys
from unittest.mock import MagicMock, patch

import pytest
from data_platform.jobs.graph.neo4j_sync import (
    _MERGE_EDGES_CYPHER_TMPL,
    BATCH_SIZE,
    DELETE_STALE_NODES_CYPHER,
    EDGE_KIND_TO_REL,
    MERGE_NODES_CYPHER,
    _chunked,
    _resolve_neo4j_config,
    parse_bolt_config,
)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------------------
# Mapeamento kind -> relacionamento
# ---------------------------------------------------------------------------
class TestKindToRel:
    def test_cobre_os_tres_tipos_de_aresta(self):
        assert EDGE_KIND_TO_REL["co_mention"] == "CO_MENTIONED_WITH"
        assert EDGE_KIND_TO_REL["subordinate_to"] == "SUBORDINATE_TO"
        assert EDGE_KIND_TO_REL["is_agency"] == "IS_AGENCY"


# ---------------------------------------------------------------------------
# Invariantes do Cypher (idempotencia)
# ---------------------------------------------------------------------------
class TestCypherInvariants:
    def test_nos_usam_merge_por_entity_id(self):
        """MERGE por entity_id garante idempotencia (nao duplica nos)."""
        norm = _normalize(MERGE_NODES_CYPHER)
        assert "merge (e:entity {entity_id: row.entity_id})" in norm
        # nao deve usar CREATE (que duplicaria a cada run)
        assert "create (e:entity" not in norm

    def test_nos_setam_as_propriedades_esperadas(self):
        norm = _normalize(MERGE_NODES_CYPHER)
        for prop in ("e.name", "e.type", "e.wikidata_id", "e.agency_key"):
            assert prop in norm

    def test_arestas_usam_match_dos_nos_e_merge_do_rel(self):
        """Arestas: MATCH src/dst (nao MERGE de no) + MERGE do relacionamento."""
        cypher = _MERGE_EDGES_CYPHER_TMPL.format(rel_type="CO_MENTIONED_WITH")
        norm = _normalize(cypher)
        assert "match (src:entity {entity_id: row.src_id})" in norm
        assert "match (dst:entity {entity_id: row.dst_id})" in norm
        assert "merge (src)-[r:co_mentioned_with]->(dst)" in norm

    def test_arestas_setam_pesos(self):
        cypher = _MERGE_EDGES_CYPHER_TMPL.format(rel_type="CO_MENTIONED_WITH")
        norm = _normalize(cypher)
        for prop in ("r.weight", "r.article_count", "r.first_seen", "r.last_seen"):
            assert prop in norm

    def test_template_de_aresta_injeta_o_rel_type(self):
        cypher = _MERGE_EDGES_CYPHER_TMPL.format(rel_type="SUBORDINATE_TO")
        assert "[r:SUBORDINATE_TO]" in cypher

    def test_cleanup_remove_nos_fora_do_conjunto_valido(self):
        """O cleanup deleta :Entity cujo entity_id NAO esta no conjunto corrente."""
        norm = _normalize(DELETE_STALE_NODES_CYPHER)
        assert "match (e:entity)" in norm
        assert "where not e.entity_id in $valid_ids" in norm
        assert "detach delete e" in norm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class TestChunked:
    def test_divide_em_lotes(self):
        assert list(_chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_lista_vazia(self):
        assert list(_chunked([], 10)) == []


class TestResolveConfig:
    def test_extrai_url_user_password(self):
        cfg = {"url": "bolt://10.0.0.5:7687", "user": "neo4j", "password": "s3cr3t"}
        assert _resolve_neo4j_config(cfg) == ("bolt://10.0.0.5:7687", "neo4j", "s3cr3t")

    def test_aceita_uri_como_alias_de_url(self):
        cfg = {"uri": "bolt://x:7687", "password": "p"}
        url, user, _ = _resolve_neo4j_config(cfg)
        assert url == "bolt://x:7687"
        assert user == "neo4j"  # default

    def test_falha_sem_password(self):
        with pytest.raises(ValueError):
            _resolve_neo4j_config({"url": "bolt://x:7687"})

    def test_falha_sem_url(self):
        with pytest.raises(ValueError):
            _resolve_neo4j_config({"password": "p"})


class TestParseBoltConfig:
    def test_dict_passthrough(self):
        d = {"url": "bolt://x", "password": "p"}
        assert parse_bolt_config(d) is d

    def test_json_string(self):
        assert parse_bolt_config('{"url": "bolt://x", "password": "p"}') == {
            "url": "bolt://x",
            "password": "p",
        }


# ---------------------------------------------------------------------------
# Orquestracao (driver/session/engine mockados)
# ---------------------------------------------------------------------------
class TestSyncOrchestration:
    def _install_fake_neo4j(self, driver):
        """Injeta um modulo `neo4j` falso (nao instalado localmente)."""
        fake = MagicMock()
        fake.GraphDatabase.driver.return_value = driver
        return patch.dict(sys.modules, {"neo4j": fake}), fake

    def test_merge_nos_antes_de_arestas_e_agrupa_por_rel(self):
        from data_platform.jobs.graph import neo4j_sync

        session = MagicMock()
        # session usado como context manager
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value = session

        nodes = [
            {"entity_id": "Q1", "name": "A", "type": "ORG", "wikidata_id": "Q1", "agency_key": "a"},
            {
                "entity_id": "Q2",
                "name": "B",
                "type": "PER",
                "wikidata_id": None,
                "agency_key": None,
            },
        ]
        edges = [
            {
                "src_id": "Q1",
                "dst_id": "Q2",
                "kind": "co_mention",
                "weight": 3,
                "article_count": 3,
                "first_seen": "2025-01-01",
                "last_seen": "2025-02-01",
            },
            {
                "src_id": "Q1",
                "dst_id": "Q2",
                "kind": "subordinate_to",
                "weight": 0,
                "article_count": 0,
                "first_seen": None,
                "last_seen": None,
            },
            {
                "src_id": "Q9",
                "dst_id": "Q9",
                "kind": "lixo_desconhecido",
                "weight": 1,
                "article_count": 1,
                "first_seen": None,
                "last_seen": None,
            },
        ]

        patcher, _ = self._install_fake_neo4j(driver)
        with patcher, patch.object(neo4j_sync, "fetch_nodes", return_value=nodes), patch.object(
            neo4j_sync, "fetch_edges", return_value=edges
        ):
            result = neo4j_sync.sync_graph_to_neo4j(
                "postgresql://x", {"url": "bolt://x:7687", "user": "neo4j", "password": "p"}
            )

        assert result["nodes"] == 2
        assert result["edges"] == {"CO_MENTIONED_WITH": 1, "SUBORDINATE_TO": 1}
        # aresta de kind desconhecido foi ignorada (nao virou rel)
        assert "lixo_desconhecido" not in result["edges"]

        # Verifica que houve a criacao da constraint de unicidade (idempotencia rapida).
        constraint_calls = [
            c
            for c in session.run.call_args_list
            if "CONSTRAINT" in str(c.args[0]) and "IS UNIQUE" in str(c.args[0])
        ]
        assert constraint_calls, "deve criar CONSTRAINT entity_id IS UNIQUE"

        driver.close.assert_called_once()

    def test_cleanup_deleta_nos_stale_com_valid_ids(self):
        """Após o MERGE, roda o DELETE de nós stale com os entity_ids correntes."""
        from data_platform.jobs.graph import neo4j_sync

        session = MagicMock()
        session.run.return_value.single.return_value = {"deleted": 4}
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value = session

        nodes = [
            {"entity_id": "Q1", "name": "A", "type": "ORG", "wikidata_id": "Q1", "agency_key": None},
            {"entity_id": "Q2", "name": "B", "type": "PER", "wikidata_id": None, "agency_key": None},
        ]

        patcher, _ = self._install_fake_neo4j(driver)
        with patcher, patch.object(neo4j_sync, "fetch_nodes", return_value=nodes), patch.object(
            neo4j_sync, "fetch_edges", return_value=[]
        ):
            result = neo4j_sync.sync_graph_to_neo4j(
                "postgresql://x", {"url": "bolt://x:7687", "password": "p"}
            )

        # achou a chamada de DELETE com valid_ids = ids dos nós sincronizados
        delete_calls = [
            c for c in session.run.call_args_list if "DETACH DELETE" in str(c.args[0])
        ]
        assert len(delete_calls) == 1
        assert delete_calls[0].kwargs["valid_ids"] == ["Q1", "Q2"]
        assert result["deleted_stale"] == 4

    def test_cleanup_pulado_quando_fetch_nodes_vazio(self):
        """GUARD: fetch_nodes vazio NUNCA dispara o DELETE (não zera o grafo)."""
        from data_platform.jobs.graph import neo4j_sync

        session = MagicMock()
        driver = MagicMock()
        driver.session.return_value.__enter__.return_value = session

        patcher, _ = self._install_fake_neo4j(driver)
        with patcher, patch.object(neo4j_sync, "fetch_nodes", return_value=[]), patch.object(
            neo4j_sync, "fetch_edges", return_value=[]
        ):
            result = neo4j_sync.sync_graph_to_neo4j(
                "postgresql://x", {"url": "bolt://x", "password": "p"}
            )

        delete_calls = [
            c for c in session.run.call_args_list if "DETACH DELETE" in str(c.args[0])
        ]
        assert delete_calls == []
        assert result["deleted_stale"] == 0

    def test_driver_fechado_mesmo_com_erro(self):
        from data_platform.jobs.graph import neo4j_sync

        driver = MagicMock()
        driver.session.side_effect = RuntimeError("boom")

        patcher, _ = self._install_fake_neo4j(driver)
        with patcher, patch.object(neo4j_sync, "fetch_nodes", return_value=[]), patch.object(
            neo4j_sync, "fetch_edges", return_value=[]
        ):
            with pytest.raises(RuntimeError):
                neo4j_sync.sync_graph_to_neo4j(
                    "postgresql://x", {"url": "bolt://x", "password": "p"}
                )

        driver.close.assert_called_once()


def test_batch_size_positivo():
    assert BATCH_SIZE > 0
