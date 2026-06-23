"""Testes estruturais (AST) da DAG compute_entity_trending."""

import ast
from pathlib import Path

DAG_FILE = Path("src/data_platform/dags/compute_entity_trending.py")


def _source() -> str:
    return DAG_FILE.read_text()


def _parse() -> ast.Module:
    return ast.parse(_source())


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
