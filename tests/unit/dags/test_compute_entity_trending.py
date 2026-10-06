"""Testes da DAG compute_entity_trending.

Airflow não está instalado localmente: os testes estruturais usam AST e o teste
de comportamento carrega o módulo com decorators do Airflow falsos, capturando a
função da task para executá-la com os jobs mockados.
"""

import ast
import importlib.util
import logging
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

DAG_FILE = Path("src/data_platform/dags/compute_entity_trending.py")
TREND_PKG = "data_platform.jobs.trend_detection"


def _source() -> str:
    return DAG_FILE.read_text()


def _parse() -> ast.Module:
    return ast.parse(_source())


def _calls(name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(_parse())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


class TestComputeEntityTrendingDAG:
    def test_airflow_nao_importado_no_topo(self):
        tree = _parse()
        top_level_imports = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
        for node in top_level_imports:
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("airflow")
            else:
                for alias in node.names:
                    assert not alias.name.startswith("airflow")

    def test_usa_postgres_default(self):
        assert 'get_connection("postgres_default")' in _source()

    def test_dag_id_correto(self):
        assert 'dag_id="compute_entity_trending"' in _source()

    def test_schedule_correto(self):
        assert 'schedule="0 */6 * * *"' in _source()

    def test_max_active_runs_1(self):
        assert "max_active_runs=1" in _source()


class TestBaselineEVersao:
    def test_dag_chama_resolve_baseline_window(self):
        assert len(_calls("resolve_baseline_window")) == 1

    def test_load_snapshot_recebe_baseline_resolvido(self):
        (call,) = _calls("load_snapshot")
        keywords = {kw.arg for kw in call.keywords}
        assert {"date_end", "baseline_start", "baseline_end"} <= keywords

    def test_so_importa_o_pacote_trend_detection_do_data_platform(self):
        """O Composer só recebe jobs/trend_detection como plugin (composer-deploy-dags.yaml)."""
        modules = [
            node.module or "" for node in ast.walk(_parse()) if isinstance(node, ast.ImportFrom)
        ]
        for module in modules:
            if module.startswith("data_platform"):
                assert module.startswith(TREND_PKG), module


def _fake_airflow(captured: dict) -> dict[str, types.ModuleType]:
    def dag(**_kwargs):
        return lambda fn: fn

    def task(**_kwargs):
        def decorator(fn):
            captured["run"] = fn
            return lambda *a, **k: None

        return decorator

    base_hook = MagicMock()
    base_hook.get_connection.return_value.get_uri.return_value = "postgres://u@h/db"
    captured["base_hook"] = base_hook

    airflow = types.ModuleType("airflow")
    decorators = types.ModuleType("airflow.decorators")
    decorators.dag = dag
    decorators.task = task
    hooks = types.ModuleType("airflow.hooks")
    hooks_base = types.ModuleType("airflow.hooks.base")
    hooks_base.BaseHook = base_hook
    return {
        "airflow": airflow,
        "airflow.decorators": decorators,
        "airflow.hooks": hooks,
        "airflow.hooks.base": hooks_base,
    }


def _load_task() -> tuple:
    captured: dict = {}
    with patch.dict(sys.modules, _fake_airflow(captured)):
        spec = importlib.util.spec_from_file_location("_dag_compute_entity_trending", DAG_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return captured["run"], captured["base_hook"]


class TestExecucaoDaTask:
    def test_usa_baseline_resolvido_e_loga_versao(self, caplog):
        run, base_hook = _load_task()
        snapshot = {"entity_stats": {"Q1": {}}, "oracle_labels": {}}
        baseline = (date(2026, 6, 6), date(2026, 7, 4))

        with (
            patch(f"{TREND_PKG}.signals.resolve_baseline_window", return_value=baseline) as resolve,
            patch(f"{TREND_PKG}.signals.load_snapshot", return_value=snapshot) as load,
            patch(f"{TREND_PKG}.scorer.compute_scores", return_value=[("Q1", 2.0)]) as score,
            patch(f"{TREND_PKG}.persist.upsert_trending_scores", return_value=1) as upsert,
            caplog.at_level(logging.INFO),
        ):
            result = run()

        base_hook.get_connection.assert_called_once_with("postgres_default")
        (date_end,), _ = resolve.call_args
        assert isinstance(date_end, date)
        load.assert_called_once_with(
            "postgresql://u@h/db",
            date_end=date_end,
            baseline_start=date(2026, 6, 6),
            baseline_end=date(2026, 7, 4),
            compute_embeddings=False,
        )
        score.assert_called_once_with(snapshot)
        upsert.assert_called_once_with("postgresql://u@h/db", [("Q1", 2.0)], {"Q1": {}})
        assert result == {"status": "ok", "count": 1}
        assert "trend_detection v2 (laplace, snapshot)" in caplog.text
        assert "2026-06-06" in caplog.text
