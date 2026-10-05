"""Testes unitarios de signals.py (trend detection): Laplace, dias ativos e baseline D2."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.trend_detection.signals import (
    TREND_DETECTION_VERSION,
    build_entity_stats,
    build_oracle_labels,
    laplace_volume_ratio,
    load_snapshot,
    resolve_baseline_window,
)

W, B = 7, 28


def _row(
    entity_id="Q1",
    canonical_name="Org A",
    entity_type="ORG",
    window_count=3,
    baseline_count=0,
    window_agencies=2,
    baseline_agencies=0,
    window_active_days=3,
):
    """Linha no formato do SELECT de load_snapshot."""
    return (
        entity_id,
        canonical_name,
        entity_type,
        window_count,
        baseline_count,
        window_agencies,
        baseline_agencies,
        window_active_days,
    )


class TestLaplaceVolumeRatio:
    def test_baseline_zero_com_tres_artigos(self):
        assert laplace_volume_ratio(3, 0, W, B) == pytest.approx(16.0)

    def test_baseline_zero_com_sessenta_artigos(self):
        assert laplace_volume_ratio(60, 0, W, B) == pytest.approx(244.0)

    def test_com_baseline(self):
        assert laplace_volume_ratio(20, 40, W, B) == pytest.approx(2.05, abs=0.005)

    def test_sem_piso_0001(self):
        """O piso antigo (baseline_daily=0.001) daria 3/7/0.001 ≈ 428,6."""
        assert laplace_volume_ratio(3, 0, W, B) < 20


class TestBuildEntityStats:
    def test_volume_ratio_laplace_e_baseline_daily_sem_piso(self):
        stats = build_entity_stats([_row(window_count=3, baseline_count=0)], W, B)
        s = stats["Q1"]
        assert s["baseline_daily"] == 0.0
        assert s["window_daily"] == pytest.approx(3 / 7)
        assert s["volume_ratio"] == pytest.approx(16.0)

    def test_propaga_contagens_e_window_active_days(self):
        row = _row(
            window_count=20,
            baseline_count=40,
            window_agencies=5,
            baseline_agencies=3,
            window_active_days=4,
        )
        s = build_entity_stats([row], W, B)["Q1"]
        assert s["canonical_name"] == "Org A"
        assert s["entity_type"] == "ORG"
        assert s["window_count"] == 20
        assert s["baseline_count"] == 40
        assert s["window_agencies"] == 5
        assert s["baseline_agencies"] == 3
        assert s["window_active_days"] == 4
        assert s["volume_ratio"] == pytest.approx(2.05, abs=0.005)
        assert s["semantic_novelty"] == 0.0
        assert s["new_edge_count"] == 0

    def test_is_new_quando_baseline_zero(self):
        stats = build_entity_stats(
            [_row("Q_novo", baseline_count=0), _row("Q_velho", baseline_count=5)], W, B
        )
        assert stats["Q_novo"]["is_new"] is True
        assert stats["Q_velho"]["is_new"] is False

    def test_usa_baseline_days_informado(self):
        """Com override, a duração efetiva do baseline entra no Laplace."""
        s = build_entity_stats([_row(window_count=3, baseline_count=0)], W, 14)["Q1"]
        assert s["volume_ratio"] == pytest.approx((4 / 7) / (1 / 14))

    def test_lista_vazia(self):
        assert build_entity_stats([], W, B) == {}


class TestBuildOracleLabels:
    def _stats(self, **overrides):
        s = build_entity_stats([_row(window_agencies=3, baseline_agencies=1)], W, B)["Q1"]
        s.update(overrides)
        return {"Q1": s}

    def test_usa_volume_ratio_do_snapshot(self):
        """wc=3, bc=9: a razão crua seria 1,33 (falso); a de Laplace é 1,6 (verdadeiro)."""
        stats = self._stats(
            window_count=3,
            baseline_count=9,
            window_daily=3 / 7,
            baseline_daily=9 / 28,
            volume_ratio=laplace_volume_ratio(3, 9, W, B),
        )
        assert build_oracle_labels(stats, min_window_articles=3) == {"Q1": True}

    def test_volume_ratio_baixo_e_falso(self):
        stats = self._stats(volume_ratio=1.4)
        assert build_oracle_labels(stats, min_window_articles=3) == {"Q1": False}

    def test_loc_e_sempre_falso(self):
        stats = self._stats(entity_type="LOC")
        assert build_oracle_labels(stats, min_window_articles=3) == {"Q1": False}

    def test_sem_crescimento_de_agencias_e_falso(self):
        stats = self._stats(window_agencies=1, baseline_agencies=1)
        assert build_oracle_labels(stats, min_window_articles=3) == {"Q1": False}

    def test_baseline_agencies_alto_e_falso(self):
        stats = self._stats(window_agencies=25, baseline_agencies=21)
        assert build_oracle_labels(stats, min_window_articles=3) == {"Q1": False}


class TestResolveBaselineWindow:
    """D2: baseline pré-defeso [06/06, 04/07) para 26/10 ≤ date_end < 30/11."""

    PRE_DEFESO = (date(2026, 6, 6), date(2026, 7, 4))

    def test_antes_da_recuperacao_e_rolante(self):
        assert resolve_baseline_window(date(2026, 10, 20)) == (
            date(2026, 9, 15),
            date(2026, 10, 13),
        )

    def test_ultimo_dia_do_defeso_ainda_e_rolante(self):
        assert resolve_baseline_window(date(2026, 10, 25)) == (
            date(2026, 9, 20),
            date(2026, 10, 18),
        )

    def test_primeiro_dia_da_recuperacao_usa_pre_defeso(self):
        assert resolve_baseline_window(date(2026, 10, 26)) == self.PRE_DEFESO

    def test_ultimo_dia_da_recuperacao_usa_pre_defeso(self):
        assert resolve_baseline_window(date(2026, 11, 29)) == self.PRE_DEFESO

    def test_trinta_de_novembro_volta_ao_rolante(self):
        """Em 30/11 o baseline rolante [26/10, 23/11) já é todo pós-defeso."""
        assert resolve_baseline_window(date(2026, 11, 30)) == (
            date(2026, 10, 26),
            date(2026, 11, 23),
        )

    def test_pre_defeso_tem_duracao_do_baseline(self):
        start, end = resolve_baseline_window(date(2026, 11, 1))
        assert (end - start).days == 28

    def test_defaults_sao_sete_e_vinte_e_oito(self):
        assert resolve_baseline_window(date(2026, 10, 20)) == resolve_baseline_window(
            date(2026, 10, 20), window_days=7, baseline_days=28
        )


def _mock_connect(mock_connect, *fetchall_results):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchall.side_effect = list(fetchall_results)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    mock_connect.return_value = conn
    return conn, cursor


class TestLoadSnapshot:
    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_sql_conta_dias_ativos_em_brt(self, mock_connect):
        _, cursor = _mock_connect(mock_connect, [])
        load_snapshot("postgresql://x", date_end=date(2026, 10, 5))
        sql = cursor.execute.call_args_list[0][0][0]
        assert "window_active_days" in sql
        assert "AT TIME ZONE 'America/Sao_Paulo'" in sql

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_baseline_rolante_por_padrao(self, mock_connect):
        _, cursor = _mock_connect(mock_connect, [])
        load_snapshot("postgresql://x", date_end=date(2026, 10, 5))
        params = cursor.execute.call_args_list[0][0][1]
        assert params["window_start"] == date(2026, 9, 28)
        assert params["date_end"] == date(2026, 10, 5)
        assert params["baseline_start"] == date(2026, 8, 31)
        assert params["baseline_end"] == date(2026, 9, 28)

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_aceita_override_de_baseline(self, mock_connect):
        rows = [_row(window_count=3, baseline_count=0, window_active_days=2)]
        _, cursor = _mock_connect(mock_connect, rows, [])
        data = load_snapshot(
            "postgresql://x",
            date_end=date(2026, 10, 26),
            baseline_start=date(2026, 6, 6),
            baseline_end=date(2026, 7, 4),
        )
        params = cursor.execute.call_args_list[0][0][1]
        assert params["baseline_start"] == date(2026, 6, 6)
        assert params["baseline_end"] == date(2026, 7, 4)
        s = data["entity_stats"]["Q1"]
        assert s["window_active_days"] == 2
        assert s["volume_ratio"] == pytest.approx(16.0)
        assert data["oracle_labels"] == {"Q1": True}

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_override_usa_duracao_efetiva_do_baseline(self, mock_connect):
        rows = [_row(window_count=3, baseline_count=0)]
        _mock_connect(mock_connect, rows, [])
        data = load_snapshot(
            "postgresql://x",
            date_end=date(2026, 10, 26),
            baseline_start=date(2026, 6, 20),
            baseline_end=date(2026, 7, 4),
        )
        assert data["entity_stats"]["Q1"]["volume_ratio"] == pytest.approx((4 / 7) / (1 / 14))

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_override_parcial_e_erro(self, mock_connect):
        with pytest.raises(ValueError):
            load_snapshot(
                "postgresql://x", date_end=date(2026, 10, 26), baseline_start=date(2026, 6, 6)
            )
        mock_connect.assert_not_called()

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_override_sobreposto_a_janela_e_erro(self, mock_connect):
        with pytest.raises(ValueError):
            load_snapshot(
                "postgresql://x",
                date_end=date(2026, 10, 26),
                baseline_start=date(2026, 10, 1),
                baseline_end=date(2026, 10, 22),
            )
        mock_connect.assert_not_called()

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_sem_linhas_retorna_vazio_e_fecha_conexao(self, mock_connect):
        conn, _ = _mock_connect(mock_connect, [])
        data = load_snapshot("postgresql://x", date_end=date(2026, 10, 5))
        assert data == {"entity_stats": {}, "oracle_labels": {}}
        conn.close.assert_called_once()

    @patch("data_platform.jobs.trend_detection.signals.psycopg2.connect")
    def test_propaga_new_edge_count(self, mock_connect):
        rows = [_row("Q1"), _row("Q2", canonical_name="Org B")]
        _mock_connect(mock_connect, rows, [("Q2", 4)])
        data = load_snapshot("postgresql://x", date_end=date(2026, 10, 5))
        assert data["entity_stats"]["Q1"]["new_edge_count"] == 0
        assert data["entity_stats"]["Q2"]["new_edge_count"] == 4


def test_versao_identifica_laplace_e_snapshot():
    assert TREND_DETECTION_VERSION == "trend_detection v2 (laplace, snapshot)"
