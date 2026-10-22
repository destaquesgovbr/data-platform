"""Testes da DAG project_entity_graph (chave de quase-duplicata antes do grafo, DP-1b).

Airflow não está instalado localmente: os testes estruturais usam AST e os de comportamento
carregam o módulo com decorators do Airflow falsos, capturando as funções das tasks e os nós
retornados (MagicMock), para conferir a dependência `compute_content_keys >> project_graph`.
"""

import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

DAG_FILE = Path("src/data_platform/dags/project_entity_graph.py")
GRAPH_PKG = "data_platform.jobs.graph"


def _source() -> str:
    return DAG_FILE.read_text()


def _parse() -> ast.Module:
    return ast.parse(_source())


def _task_decorators() -> dict[str, ast.expr]:
    """{nome da função da task: decorator @task(...)}."""
    out = {}
    for node in ast.walk(_parse()):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                if isinstance(target, ast.Name) and target.id == "task":
                    out[node.name] = deco
    return out


class TestEstrutura:
    def test_airflow_nao_importado_no_topo(self):
        for node in _parse().body:
            if isinstance(node, ast.ImportFrom):
                assert node.module is None or not node.module.startswith("airflow")
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith("airflow") for alias in node.names)

    def test_dag_id_e_schedule_inalterados(self):
        assert 'dag_id="project_entity_graph"' in _source()
        assert 'schedule="0 */6 * * *"' in _source()
        assert "max_active_runs=1" in _source()

    def test_as_duas_tasks_usam_postgres_default(self):
        calls = [
            node
            for node in ast.walk(_parse())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_connection"
        ]
        assert [c.args[0].value for c in calls] == ["postgres_default", "postgres_default"]

    def test_so_importa_o_pacote_graph_do_data_platform(self):
        """O Composer recebe jobs/graph como plugin (composer-deploy-dags.yaml)."""
        for node in ast.walk(_parse()):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("data_platform"):
                assert node.module.startswith(GRAPH_PKG), node.module

    def test_tem_as_duas_tasks(self):
        assert set(_task_decorators()) == {"compute_content_keys", "project_graph"}

    def test_grafo_roda_mesmo_se_a_chave_falhar(self):
        """Falha na chave não congela o grafo: ele roda com a chave anterior (COALESCE)."""
        deco = _task_decorators()["project_graph"]
        assert isinstance(deco, ast.Call)
        kwargs = {kw.arg: kw.value for kw in deco.keywords}
        assert isinstance(kwargs["trigger_rule"], ast.Constant)
        assert kwargs["trigger_rule"].value == "all_done"


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


def _load() -> dict:
    captured: dict = {}
    with patch.dict(sys.modules, _fake_airflow(captured)):
        spec = importlib.util.spec_from_file_location("_dag_project_entity_graph", DAG_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return captured


class TestExecucao:
    def test_chave_de_conteudo_roda_antes_do_grafo(self):
        nodes = _load()["nodes"]

        nodes["compute_content_keys"].__rshift__.assert_called_once_with(nodes["project_graph"])

    def test_compute_content_keys_recalcula_a_janela_padrao(self):
        captured = _load()

        with patch(
            f"{GRAPH_PKG}.content_keys.run_content_keys", return_value={"changes": 3}
        ) as run:
            result = captured["compute_content_keys"]()

        captured["base_hook"].get_connection.assert_called_with("postgres_default")
        run.assert_called_once_with("postgresql://u@h/db")
        assert result == {"changes": 3}

    def test_project_graph_continua_chamando_a_projecao(self):
        captured = _load()

        with patch(
            f"{GRAPH_PKG}.edges.project_entity_graph", return_value={"status": "ok"}
        ) as projection:
            result = captured["project_graph"]()

        projection.assert_called_once_with("postgresql://u@h/db")
        assert result == {"status": "ok"}
