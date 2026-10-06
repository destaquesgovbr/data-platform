"""Testes unitarios de compute_scores (trend detection)."""

import pytest

from data_platform.jobs.trend_detection.scorer import compute_scores
from data_platform.jobs.trend_detection.signals import build_entity_stats


def _make_entity(
    entity_type="ORG",
    window_count=5,
    volume_ratio=2.5,
    window_agencies=5,
    baseline_agencies=3,
    semantic_novelty=0.3,
    window_active_days=3,
):
    return {
        "canonical_name": "Test Org",
        "entity_type": entity_type,
        "window_count": window_count,
        "baseline_count": 22,
        # coerentes com volume_ratio: o scorer antigo recalculava a razão a partir deles
        "window_daily": volume_ratio * 22 / 28,
        "baseline_daily": 22 / 28,
        "volume_ratio": volume_ratio,
        "is_new": False,
        "window_active_days": window_active_days,
        "window_agencies": window_agencies,
        "baseline_agencies": baseline_agencies,
        "semantic_novelty": semantic_novelty,
        "new_edge_count": 2,
    }


def _score(volume_ratio, window_agencies, baseline_agencies, semantic_novelty):
    """Fórmula atual (pesos calibrados para o vr cru; D1 pendente)."""
    agency_growth = window_agencies / max(baseline_agencies, 1)
    niche = 1.0 / (1.0 + baseline_agencies)
    return (
        0.40 * volume_ratio
        + 0.25 * agency_growth
        + 0.20 * niche * volume_ratio
        + 0.15 * semantic_novelty
    )


class TestComputeScores:
    def test_filtra_loc(self):
        data = {"entity_stats": {"Q1": _make_entity(entity_type="LOC")}}
        assert compute_scores(data) == []

    def test_filtra_window_count_baixo(self):
        data = {"entity_stats": {"Q1": _make_entity(window_count=2)}}
        assert compute_scores(data) == []

    def test_filtra_volume_ratio_baixo(self):
        data = {"entity_stats": {"Q1": _make_entity(volume_ratio=1.5)}}
        assert compute_scores(data) == []

    def test_filtra_baseline_agencies_alto(self):
        data = {
            "entity_stats": {
                "Q1": _make_entity(window_agencies=22, baseline_agencies=21),
            }
        }
        assert compute_scores(data) == []

    def test_filtra_sem_crescimento_agency(self):
        data = {
            "entity_stats": {
                "Q1": _make_entity(window_agencies=3, baseline_agencies=3),
            }
        }
        assert compute_scores(data) == []

    def test_ordenacao_por_score_desc(self):
        data = {
            "entity_stats": {
                "Q_low": _make_entity(volume_ratio=1.8),
                "Q_high": _make_entity(volume_ratio=8.0),
            }
        }
        result = compute_scores(data)
        assert [eid for eid, _ in result] == ["Q_high", "Q_low"]
        assert result[0][1] > result[1][1]

    def test_retorna_vazio_quando_sem_entidades_validas(self):
        data = {
            "entity_stats": {
                "Q1": _make_entity(entity_type="LOC"),
                "Q2": _make_entity(window_count=1),
            }
        }
        assert compute_scores(data) == []

    def test_entidade_valida_passa_todos_filtros(self):
        data = {"entity_stats": {"Q1": _make_entity()}}
        result = compute_scores(data)
        assert len(result) == 1
        assert result[0][0] == "Q1"
        assert result[0][1] > 0


class TestVolumeRatioDoSnapshot:
    def test_usa_volume_ratio_do_snapshot(self):
        """window_daily == baseline_daily daria razão 1,0; vale o volume_ratio do snapshot."""
        entity = _make_entity(volume_ratio=3.0)
        entity["window_daily"] = entity["baseline_daily"] = 1.0
        result = compute_scores({"entity_stats": {"Q1": entity}})
        assert result == [("Q1", pytest.approx(_score(3.0, 5, 3, 0.3)))]

    def test_baseline_zero_sem_zerodivision(self):
        entity = _make_entity(volume_ratio=16.0, baseline_agencies=0, window_agencies=2)
        entity.update(baseline_count=0, baseline_daily=0.0, is_new=True)
        result = compute_scores({"entity_stats": {"Q1": entity}})
        assert result == [("Q1", pytest.approx(_score(16.0, 2, 0, 0.3)))]


class TestFiltroDeDiasAtivos:
    def test_filtra_burst_de_um_dia(self):
        data = {"entity_stats": {"Q1": _make_entity(window_active_days=1)}}
        assert compute_scores(data) == []

    def test_dois_dias_ativos_passa(self):
        data = {"entity_stats": {"Q1": _make_entity(window_active_days=2)}}
        assert [eid for eid, _ in compute_scores(data)] == ["Q1"]

    def test_sem_window_active_days_e_descartado(self):
        entity = _make_entity()
        del entity["window_active_days"]
        assert compute_scores({"entity_stats": {"Q1": entity}}) == []

    def test_caso_censo_57_3_passa_no_filtro_e_lidera(self):
        """Documenta o comportamento ATUAL (antes da decisão D1).

        Censo: 60 artigos na janela, 57 no mesmo dia e 3 em outros dias, baseline zero.
        O filtro de >= 2 dias ativos não pega esse caso: com vr = 244 (Laplace) e os
        pesos calibrados para o vr cru, o Censo fica muito à frente de uma tendência
        real (vr ~2). A guarda de rajada por max_day_share (D4) está no gobus; o
        log1p(vr) e o limite do agency_growth (D1) aguardam o evaluate.py. Quando a
        D1 entrar, este teste deve ser revisto de propósito.
        """
        rows = [
            # entity_id, nome, tipo, wc, bc, wa, ba, dias ativos
            ("Q_censo", "Censo", "EVENT", 60, 0, 3, 0, 4),
            ("Q_real", "Tendência real", "POLICY", 20, 40, 6, 3, 7),
        ]
        data = {"entity_stats": build_entity_stats(rows, 7, 28)}
        data["entity_stats"]["Q_censo"]["semantic_novelty"] = 0.0
        data["entity_stats"]["Q_real"]["semantic_novelty"] = 0.0

        result = compute_scores(data)

        assert [eid for eid, _ in result] == ["Q_censo", "Q_real"]
        censo_score = dict(result)["Q_censo"]
        assert censo_score == pytest.approx(_score(244.0, 3, 0, 0.0))
        assert censo_score > 100
