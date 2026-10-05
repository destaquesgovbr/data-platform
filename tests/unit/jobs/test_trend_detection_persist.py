"""Testes unitarios de upsert_trending_scores (trend detection)."""

from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.trend_detection.persist import upsert_trending_scores


def _mock_engine(mock_create_engine):
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_create_engine.return_value = mock_engine
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine, mock_conn


def _stats(name="Org A", **overrides):
    s = {
        "canonical_name": name,
        "entity_type": "ORG",
        "window_count": 5,
        "baseline_count": 22,
        "window_daily": 5 / 7,
        "baseline_daily": 22 / 28,
        "volume_ratio": 1.04,
        "is_new": False,
        "window_active_days": 3,
        "window_agencies": 4,
        "baseline_agencies": 2,
        "semantic_novelty": 0.0,
        "new_edge_count": 0,
    }
    s.update(overrides)
    return s


def _sql(call) -> str:
    return " ".join(str(call.args[0]).split())


def _upsert_calls(mock_conn):
    return [c for c in mock_conn.execute.call_args_list if "INSERT INTO" in _sql(c)]


def _delete_calls(mock_conn):
    return [c for c in mock_conn.execute.call_args_list if "DELETE FROM" in _sql(c)]


class TestUpsertTrendingScores:
    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_retorna_zero_para_lista_vazia(self, mock_create_engine):
        count = upsert_trending_scores("postgresql://test", [], {})
        assert count == 0
        mock_create_engine.assert_not_called()

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_upsert_em_lote_com_executemany(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        scores = [("Q1", 3.5), ("Q2", 2.1)]
        entity_stats = {"Q1": _stats("Org A"), "Q2": _stats("Person B", entity_type="PER")}
        count = upsert_trending_scores("postgresql://test", scores, entity_stats)

        assert count == 2
        upserts = _upsert_calls(mock_conn)
        assert len(upserts) == 1
        params = upserts[0].args[1]
        assert [p["entity_id"] for p in params] == ["Q1", "Q2"]
        assert [p["score"] for p in params] == [3.5, 2.1]

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_ignora_entity_sem_canonical_name(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        entity_stats = {"Q1": _stats(name=None)}
        count = upsert_trending_scores("postgresql://test", [("Q1", 3.5)], entity_stats)
        assert count == 0
        assert _upsert_calls(mock_conn) == []

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_engine_disposed_ao_final(self, mock_create_engine):
        mock_engine, _ = _mock_engine(mock_create_engine)

        upsert_trending_scores("postgresql://test", [("Q1", 3.5)], {"Q1": _stats()})
        mock_engine.dispose.assert_called_once()

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_engine_disposed_quando_falha(self, mock_create_engine):
        mock_engine, mock_conn = _mock_engine(mock_create_engine)
        mock_conn.execute.side_effect = RuntimeError("db fora")

        with pytest.raises(RuntimeError):
            upsert_trending_scores("postgresql://test", [("Q1", 3.5)], {"Q1": _stats()})
        mock_engine.dispose.assert_called_once()


class TestBaselineEVolumeRatio:
    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_grava_baseline(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        stats = {"Q1": _stats(baseline_count=40, baseline_agencies=3)}
        upsert_trending_scores("postgresql://test", [("Q1", 3.5)], stats)

        upsert = _upsert_calls(mock_conn)[0]
        sql = _sql(upsert)
        assert "baseline_count" in sql
        assert "baseline_agencies" in sql
        assert "baseline_count = EXCLUDED.baseline_count" in sql
        assert "baseline_agencies = EXCLUDED.baseline_agencies" in sql
        params = upsert.args[1][0]
        assert params["baseline_count"] == 40
        assert params["baseline_agencies"] == 3

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_volume_ratio_vem_do_snapshot(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        stats = {"Q1": _stats(window_daily=2.0, baseline_daily=0.8, volume_ratio=3.3)}
        upsert_trending_scores("postgresql://test", [("Q1", 3.5)], stats)

        assert _upsert_calls(mock_conn)[0].args[1][0]["volume_ratio"] == 3.3

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_baseline_zero_sem_zerodivision(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        stats = {
            "Q1": _stats(
                baseline_count=0,
                baseline_agencies=0,
                baseline_daily=0.0,
                volume_ratio=16.0,
                is_new=True,
            )
        }
        count = upsert_trending_scores("postgresql://test", [("Q1", 9.0)], stats)

        assert count == 1
        params = _upsert_calls(mock_conn)[0].args[1][0]
        assert params["volume_ratio"] == 16.0
        assert params["baseline_count"] == 0
        assert params["baseline_agencies"] == 0


class TestSnapshotUnico:
    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_delete_stale_na_mesma_transacao_apos_upsert(self, mock_create_engine):
        mock_engine, mock_conn = _mock_engine(mock_create_engine)

        upsert_trending_scores("postgresql://test", [("Q1", 3.5)], {"Q1": _stats()})

        mock_engine.begin.assert_called_once()
        sqls = [_sql(c) for c in mock_conn.execute.call_args_list]
        assert len(sqls) == 2
        assert sqls[0].startswith("INSERT INTO entity_trending_scores")
        assert sqls[1] == "DELETE FROM entity_trending_scores WHERE computed_at < NOW()"

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_scores_vazios_com_stats_limpa_snapshot(self, mock_create_engine):
        """Há dados, mas nada em alta: o snapshot fica vazio (verdadeiro)."""
        mock_engine, mock_conn = _mock_engine(mock_create_engine)

        count = upsert_trending_scores("postgresql://test", [], {"Q1": _stats()})

        assert count == 0
        mock_engine.begin.assert_called_once()
        assert _upsert_calls(mock_conn) == []
        assert len(_delete_calls(mock_conn)) == 1

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_sem_stats_nao_toca_tabela(self, mock_create_engine):
        """Falta de dado (snapshot vazio) não apaga o snapshot anterior."""
        count = upsert_trending_scores("postgresql://test", [("Q1", 3.5)], {})

        assert count == 0
        mock_create_engine.assert_not_called()
