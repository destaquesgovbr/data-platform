"""Testes unitarios de upsert_trending_scores (trend detection)."""

from unittest.mock import MagicMock, patch

from data_platform.jobs.trend_detection.persist import upsert_trending_scores


def _mock_engine(mock_create_engine):
    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_create_engine.return_value = mock_engine
    mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine, mock_conn


class TestUpsertTrendingScores:
    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_retorna_zero_para_lista_vazia(self, mock_create_engine):
        count = upsert_trending_scores("postgresql://test", [], {})
        assert count == 0

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_executa_upsert_para_cada_score(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        scores = [("Q1", 3.5), ("Q2", 2.1)]
        entity_stats = {
            "Q1": {
                "canonical_name": "Org A",
                "entity_type": "ORG",
                "window_count": 5,
                "window_agencies": 4,
                "window_daily": 2.0,
                "baseline_daily": 0.8,
            },
            "Q2": {
                "canonical_name": "Person B",
                "entity_type": "PER",
                "window_count": 3,
                "window_agencies": 2,
                "window_daily": 1.8,
                "baseline_daily": 0.9,
            },
        }
        count = upsert_trending_scores("postgresql://test", scores, entity_stats)
        assert count == 2
        assert mock_conn.execute.call_count == 2

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_ignora_entity_sem_canonical_name(self, mock_create_engine):
        _, mock_conn = _mock_engine(mock_create_engine)

        scores = [("Q1", 3.5)]
        entity_stats = {
            "Q1": {
                "entity_type": "ORG",
                "window_count": 5,
                "window_agencies": 4,
                "window_daily": 2.0,
                "baseline_daily": 0.8,
            },
        }
        count = upsert_trending_scores("postgresql://test", scores, entity_stats)
        assert count == 0
        assert mock_conn.execute.call_count == 0

    @patch("data_platform.jobs.trend_detection.persist.create_engine")
    def test_engine_disposed_ao_final(self, mock_create_engine):
        mock_engine, _ = _mock_engine(mock_create_engine)

        scores = [("Q1", 3.5)]
        entity_stats = {
            "Q1": {
                "canonical_name": "Org A",
                "entity_type": "ORG",
                "window_count": 5,
                "window_agencies": 4,
                "window_daily": 2.0,
                "baseline_daily": 0.8,
            },
        }
        upsert_trending_scores("postgresql://test", scores, entity_stats)
        mock_engine.dispose.assert_called_once()
