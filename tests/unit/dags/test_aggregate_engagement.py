"""DAG aggregate_engagement: manutenção diária de news_features (DP-1c).

Além do view_count, a DAG completa readability_flesch_ptbr nas linhas que outros escritores
criaram ou reescreveram sem a chave (task fill_flesch_ptbr). As duas tasks são
independentes: uma falha no BigQuery não segura o Flesch, e vice-versa.

Airflow não está instalado localmente: AST para a estrutura e decorators falsos para a
execução (mesmo padrão de test_project_entity_graph.py).
"""

import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

DAG_FILE = Path("src/data_platform/dags/aggregate_engagement.py")
FILL_MODULE = "data_platform.jobs.features.flesch_ptbr_fill"


def _source() -> str:
    return DAG_FILE.read_text()


def _parse() -> ast.Module:
    return ast.parse(_source())


def _task_functions() -> dict[str, ast.FunctionDef]:
    out = {}
    for node in ast.walk(_parse()):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                if isinstance(target, ast.Name) and target.id == "task":
                    out[node.name] = node
    return out


class TestEstrutura:
    def test_dag_id_e_schedule_inalterados(self):
        assert 'dag_id="aggregate_engagement"' in _source()
        assert 'schedule="0 8 * * *"' in _source()

    def test_tem_as_duas_tasks(self):
        assert set(_task_functions()) == {"aggregate_and_sync", "fill_flesch_ptbr"}

    def test_fill_so_importa_o_pacote_features_dos_plugins(self):
        """O Composer recebe jobs/features como plugin; textstat e o feature-worker não."""
        fn = _task_functions()["fill_flesch_ptbr"]
        modules = [
            node.module
            for node in ast.walk(fn)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("data_platform")
        ]
        assert modules == [FILL_MODULE]

    def test_fill_tem_timeout_proprio(self):
        deco = _task_functions()["fill_flesch_ptbr"].decorator_list[0]
        assert isinstance(deco, ast.Call)
        assert "execution_timeout" in {kw.arg for kw in deco.keywords}


def _fake_airflow(captured: dict) -> dict[str, types.ModuleType]:
    def dag(**_kwargs):
        return lambda fn: fn

    def task(fn=None, **_kwargs):
        def decorator(f):
            captured[f.__name__] = f
            node = MagicMock(name=f.__name__)
            captured.setdefault("nodes", {})[f.__name__] = node
            return lambda *a, **k: node

        return decorator(fn) if callable(fn) else decorator

    base_hook = MagicMock()
    base_hook.get_connection.return_value.get_uri.return_value = "postgres://u@h/db"
    captured["base_hook"] = base_hook

    decorators = types.ModuleType("airflow.decorators")
    decorators.dag = dag
    decorators.task = task
    hooks_base = types.ModuleType("airflow.hooks.base")
    hooks_base.BaseHook = base_hook
    models = types.ModuleType("airflow.models")
    models.Variable = MagicMock()
    return {
        "airflow": types.ModuleType("airflow"),
        "airflow.decorators": decorators,
        "airflow.hooks": types.ModuleType("airflow.hooks"),
        "airflow.hooks.base": hooks_base,
        "airflow.models": models,
    }


def _load() -> dict:
    captured: dict = {}
    with patch.dict(sys.modules, _fake_airflow(captured)):
        spec = importlib.util.spec_from_file_location("_dag_aggregate_engagement", DAG_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return captured


class TestExecucao:
    def test_tasks_independentes(self):
        nodes = _load()["nodes"]
        for node in nodes.values():
            node.__rshift__.assert_not_called()
            node.__lshift__.assert_not_called()

    def test_fill_usa_a_janela_padrao(self):
        captured = _load()

        with patch(f"{FILL_MODULE}.run_fill_flesch_ptbr", return_value={"updated": 2}) as run:
            result = captured["fill_flesch_ptbr"](dag_run=MagicMock(conf={}))

        captured["base_hook"].get_connection.assert_called_with("postgres_default")
        run.assert_called_once_with("postgresql://u@h/db", lookback_days=3)
        assert result == {"updated": 2}

    def test_conf_do_disparo_manual_troca_a_janela(self):
        """`--conf '{"flesch_lookback_days": null}'` varre a tabela inteira uma vez."""
        captured = _load()

        with patch(f"{FILL_MODULE}.run_fill_flesch_ptbr", return_value={}) as run:
            captured["fill_flesch_ptbr"](dag_run=MagicMock(conf={"flesch_lookback_days": None}))

        run.assert_called_once_with("postgresql://u@h/db", lookback_days=None)

    def test_sem_dag_run_usa_o_padrao(self):
        captured = _load()

        with patch(f"{FILL_MODULE}.run_fill_flesch_ptbr", return_value={}) as run:
            captured["fill_flesch_ptbr"]()

        run.assert_called_once_with("postgresql://u@h/db", lookback_days=3)
