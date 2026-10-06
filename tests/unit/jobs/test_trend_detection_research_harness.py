"""O harness offline de research/trend-detection é o que decide a D1 (log1p do vr e
limite do agency_growth). Para o NDCG dele valer para o DAG, signals.py e scorer.py do
harness têm de medir o código de produção (jobs/trend_detection): Laplace, dias ativos
em BRT, baseline de resolve_baseline_window e o mesmo oráculo. Cópias congeladas não.

evaluate.py faz `from signals import load_snapshot` e `from scorer import compute_scores`
a partir do próprio diretório; aqui os dois arquivos são carregados pelo caminho.
"""

import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.trend_detection.scorer import compute_scores as prod_compute_scores
from data_platform.jobs.trend_detection.signals import build_entity_stats, build_oracle_labels

ROOT = Path(__file__).resolve().parents[3]
HARNESS_DIR = ROOT / "research" / "trend-detection"
DB_URL = "postgresql://harness:harness@localhost:5432/harness"
CONNECT = "data_platform.jobs.trend_detection.signals.psycopg2.connect"
W, B = 7, 28


def _load(name: str, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    spec = importlib.util.spec_from_file_location(f"_harness_{name}", HARNESS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness_signals(monkeypatch):
    return _load("signals", monkeypatch)


@pytest.fixture
def harness_scorer(monkeypatch):
    return _load("scorer", monkeypatch)


def _mock_db(mock_connect, *fetchall_results):
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchall.side_effect = list(fetchall_results)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    mock_connect.return_value = conn
    return cursor


# (entity_id, canonical_name, type, wc, bc, window_agencies, baseline_agencies, active_days)
# Q_censo: wc=3, bc=8 → vr cru = 1,5 (o oráculo antigo dava False); Laplace = 16/9 ≈ 1,78.
ROWS = [
    ("Q_censo", "Censo", "EVENT", 3, 8, 3, 1, 2),
    ("Q_novo", "Programa Novo", "POLICY", 5, 0, 3, 0, 4),
    ("Q_rajada", "Rajada", "ORG", 12, 4, 5, 1, 1),
    ("Q_loc", "Goiás", "LOC", 9, 2, 4, 1, 3),
]


class TestSignalsDoHarness:
    @patch(CONNECT)
    def test_snapshot_e_oraculo_sao_os_de_producao(self, mock_connect, harness_signals):
        _mock_db(mock_connect, ROWS, [])

        data = harness_signals.load_snapshot(date_end=date(2026, 10, 5))

        expected = build_entity_stats(ROWS, W, B)
        assert data["entity_stats"] == expected
        assert data["oracle_labels"] == build_oracle_labels(expected, 3)
        assert data["oracle_labels"]["Q_censo"] is True
        mock_connect.assert_called_once_with(DB_URL)

    @patch(CONNECT)
    def test_sql_conta_dias_ativos_em_brt(self, mock_connect, harness_signals):
        cursor = _mock_db(mock_connect, [])

        harness_signals.load_snapshot(date_end=date(2026, 10, 5))

        sql = cursor.execute.call_args_list[0][0][0]
        assert "AT TIME ZONE 'America/Sao_Paulo'" in sql

    @pytest.mark.parametrize(
        ("date_end", "baseline"),
        [
            (date(2026, 10, 5), (date(2026, 8, 31), date(2026, 9, 28))),
            (date(2026, 10, 26), (date(2026, 6, 6), date(2026, 7, 4))),
            (date(2026, 11, 30), (date(2026, 10, 26), date(2026, 11, 23))),
        ],
        ids=["rolante", "pre-defeso", "volta-ao-rolante"],
    )
    @patch(CONNECT)
    def test_baseline_vem_de_resolve_baseline_window(
        self, mock_connect, harness_signals, date_end, baseline
    ):
        cursor = _mock_db(mock_connect, [])

        harness_signals.load_snapshot(date_end=date_end)

        params = cursor.execute.call_args_list[0][0][1]
        assert (params["baseline_start"], params["baseline_end"]) == baseline

    @patch(CONNECT)
    def test_sem_embeddings_por_padrao_como_o_dag(self, mock_connect, harness_signals):
        cursor = _mock_db(mock_connect, ROWS, [])

        data = harness_signals.load_snapshot(date_end=date(2026, 10, 5))

        queries = [call[0][0] for call in cursor.execute.call_args_list]
        assert not any("content_embedding" in sql for sql in queries)
        assert {s["semantic_novelty"] for s in data["entity_stats"].values()} == {0.0}


class TestScorerDoHarness:
    def test_ranking_e_o_do_scorer_de_producao(self, harness_scorer):
        stats = build_entity_stats(ROWS, W, B)
        data = {"entity_stats": stats, "oracle_labels": build_oracle_labels(stats, 3)}

        ranking = harness_scorer.compute_scores(data)

        assert ranking == prod_compute_scores(data)
        assert [eid for eid, _ in ranking] == ["Q_novo", "Q_censo"]

    def test_descarta_burst_de_um_dia(self, harness_scorer):
        stats = build_entity_stats([("Q_rajada", "Rajada", "ORG", 12, 4, 5, 1, 1)], W, B)

        assert harness_scorer.compute_scores({"entity_stats": stats, "oracle_labels": {}}) == []
