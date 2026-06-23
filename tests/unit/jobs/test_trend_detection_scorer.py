"""Testes unitarios de compute_scores (trend detection)."""

from data_platform.jobs.trend_detection.scorer import compute_scores


def _make_entity(
    entity_type="ORG",
    window_count=5,
    window_daily=2.0,
    baseline_daily=0.8,
    window_agencies=5,
    baseline_agencies=3,
    semantic_novelty=0.3,
):
    return {
        "canonical_name": "Test Org",
        "entity_type": entity_type,
        "window_count": window_count,
        "baseline_count": 22,
        "window_daily": window_daily,
        "baseline_daily": baseline_daily,
        "window_agencies": window_agencies,
        "baseline_agencies": baseline_agencies,
        "semantic_novelty": semantic_novelty,
        "new_edge_count": 2,
    }


class TestComputeScores:
    def test_filtra_loc(self):
        data = {"entity_stats": {"Q1": _make_entity(entity_type="LOC")}}
        assert compute_scores(data) == []

    def test_filtra_window_count_baixo(self):
        data = {"entity_stats": {"Q1": _make_entity(window_count=2)}}
        assert compute_scores(data) == []

    def test_filtra_volume_ratio_baixo(self):
        data = {"entity_stats": {"Q1": _make_entity(window_daily=1.0, baseline_daily=1.0)}}
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
                "Q_low": _make_entity(window_daily=1.8, baseline_daily=1.0),
                "Q_high": _make_entity(window_daily=4.0, baseline_daily=0.5),
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
