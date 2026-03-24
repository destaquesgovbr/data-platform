"""Testes unitários para processamento de resultados de integridade."""

import json
from unittest.mock import MagicMock, call, patch

from data_platform.jobs.integrity.results import (
    LOAD_STATE_SQL,
    UPSERT_SQL,
    _load_existing_state,
    sync_image_status_to_typesense,
    upsert_integrity_results,
)


class TestUpsertSQL:
    """Testes para a query SQL de upsert."""

    def test_uses_jsonb_set_not_shallow_merge(self):
        query_str = str(UPSERT_SQL)
        assert "jsonb_set" in query_str
        assert "integrity_fields" in query_str

    def test_merges_at_integrity_sub_object(self):
        query_str = str(UPSERT_SQL)
        assert "'{integrity}'" in query_str
        assert "news_features.features -> 'integrity'" in query_str

    def test_preserves_existing_integrity_fields_on_merge(self):
        query_str = str(UPSERT_SQL)
        assert "COALESCE(news_features.features -> 'integrity', '{}')" in query_str


class TestLoadExistingState:
    """Testes para pré-carregamento de estado em batch."""

    def test_empty_ids_returns_empty_dict(self):
        conn = MagicMock()
        result = _load_existing_state(conn, [])
        assert result == {}
        conn.execute.assert_not_called()

    def test_loads_check_count_and_image_status(self):
        conn = MagicMock()
        row = MagicMock()
        row.unique_id = "abc"
        row.check_count = 3
        row.image_status = "broken"
        conn.execute.return_value.fetchall.return_value = [row]

        result = _load_existing_state(conn, ["abc"])
        assert result == {"abc": {"check_count": 3, "image_status": "broken"}}

    def test_multiple_ids_in_single_query(self):
        conn = MagicMock()
        row1 = MagicMock(unique_id="a", check_count=1, image_status="ok")
        row2 = MagicMock(unique_id="b", check_count=0, image_status=None)
        conn.execute.return_value.fetchall.return_value = [row1, row2]

        result = _load_existing_state(conn, ["a", "b"])
        assert len(result) == 2
        assert result["a"]["check_count"] == 1
        assert result["b"]["image_status"] is None


class TestUpsertIntegrityResults:
    """Testes para a função principal de upsert."""

    def test_empty_results(self):
        result = upsert_integrity_results("postgresql://fake", [])
        assert result == {"broken_ids": [], "fixed_ids": [], "count": 0}

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_detects_broken_ids(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        results = [{"unique_id": "abc", "image_status": "broken", "image_checked_at": "2026-01-01"}]
        output = upsert_integrity_results("postgresql://fake", results)

        assert "abc" in output["broken_ids"]
        assert output["count"] == 1

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_detects_fixed_ids_when_previously_broken(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Simular estado anterior: artigo era broken
        row = MagicMock(unique_id="abc", check_count=2, image_status="broken")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        results = [{"unique_id": "abc", "image_status": "ok", "image_checked_at": "2026-01-01"}]
        output = upsert_integrity_results("postgresql://fake", results)

        assert "abc" in output["fixed_ids"]

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_does_not_mark_fixed_if_previously_ok(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Simular estado anterior: artigo já era ok
        row = MagicMock(unique_id="abc", check_count=5, image_status="ok")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        results = [{"unique_id": "abc", "image_status": "ok", "image_checked_at": "2026-01-01"}]
        output = upsert_integrity_results("postgresql://fake", results)

        assert output["fixed_ids"] == []

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_increments_check_count_from_existing_state(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        row = MagicMock(unique_id="abc", check_count=7, image_status="ok")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        results = [{"unique_id": "abc", "image_status": "ok", "image_checked_at": "2026-01-01"}]
        upsert_integrity_results("postgresql://fake", results)

        # Verificar que o upsert foi chamado com check_count=8
        upsert_call = mock_conn.execute.call_args_list[1]  # [0]=load_state, [1]=upsert
        integrity_json = upsert_call.args[1]["integrity_fields"]
        integrity = json.loads(integrity_json)
        assert integrity["check_count"] == 8

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_new_article_starts_check_count_at_1(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Artigo novo, não existe no banco
        mock_conn.execute.return_value.fetchall.return_value = []

        results = [{"unique_id": "new", "image_status": "ok", "image_checked_at": "2026-01-01"}]
        upsert_integrity_results("postgresql://fake", results)

        upsert_call = mock_conn.execute.call_args_list[1]
        integrity_json = upsert_call.args[1]["integrity_fields"]
        integrity = json.loads(integrity_json)
        assert integrity["check_count"] == 1

    @patch("data_platform.jobs.integrity.results.create_engine")
    def test_passes_integrity_fields_not_wrapped(self, mock_create_engine):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        results = [{"unique_id": "abc", "image_status": "ok", "image_checked_at": "2026-01-01"}]
        upsert_integrity_results("postgresql://fake", results)

        upsert_call = mock_conn.execute.call_args_list[1]
        integrity_json = upsert_call.args[1]["integrity_fields"]
        integrity = json.loads(integrity_json)
        # Deve ser o sub-objeto direto, não {"integrity": {...}}
        assert "integrity" not in integrity
        assert "image_status" in integrity


class TestSyncImageStatusToTypesense:
    """Testes para sincronização de status com Typesense."""

    def test_no_changes(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(client, "news", [], [])
        assert result == 0

    def test_marks_broken_images(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=["abc", "def"], fixed_ids=[]
        )
        assert result == 2

        calls = client.collections["news"].documents.__getitem__.call_args_list
        assert len(calls) == 2

    def test_marks_fixed_images(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=[], fixed_ids=["abc"]
        )
        assert result == 1

    def test_handles_typesense_error(self):
        client = MagicMock()
        client.collections.__getitem__.return_value.documents.__getitem__.return_value.update.side_effect = Exception("Not found")

        # Não deve levantar exceção
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=["abc"], fixed_ids=[]
        )
        assert result == 0
