"""Testes estruturais (AST) da DAG sync_graph_to_neo4j (Fase 6b).

Airflow nao esta instalado localmente e o modulo executa dag_instance = sync_graph_to_neo4j()
no import, entao usamos testes estruturais via AST (mesmo padrao de test_generate_video_thumbnails).
"""

import ast
from pathlib import Path

DAG_FILE = Path("src/data_platform/dags/sync_graph_to_neo4j.py")


def _parse() -> ast.Module:
    return ast.parse(DAG_FILE.read_text())


def _source() -> str:
    return DAG_FILE.read_text()


def test_neo4j_nao_importado_no_topo():
    """O driver neo4j so existe no Composer: nao pode ser import de topo (quebraria o parse)."""
    tree = _parse()
    top_level_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level_imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            top_level_imports.append(node.module or "")
    assert not any("neo4j" in (m or "") for m in top_level_imports)


def test_usa_postgres_default():
    assert 'get_connection("postgres_default")' in _source()


def test_dag_id_correto():
    assert 'dag_id="sync_graph_to_neo4j"' in _source()


def test_schedule_apos_project_entity_graph():
    """Roda 30min apos project_entity_graph (0 */6) -> 30 */6."""
    assert 'schedule="30 */6 * * *"' in _source()


def test_resolve_config_via_variable_e_fallback_env():
    src = _source()
    assert 'Variable.get("neo4j_bolt_url"' in src
    assert "NEO4J_BOLT_URL" in src


def test_delega_ao_job_neo4j_sync():
    assert "from data_platform.jobs.graph.neo4j_sync import" in _source()


def test_converte_postgres_para_postgresql():
    """Mesma normalizacao das demais DAGs (postgres:// -> postgresql://)."""
    assert 'replace("postgres://", "postgresql://", 1)' in _source()
