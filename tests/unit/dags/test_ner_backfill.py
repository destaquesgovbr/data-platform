"""Testes estruturais (AST) da DAG ner_backfill.

Airflow + provider google nao estao instalados localmente e o modulo executa
dag_instance = ner_backfill() no import (apos try/except ImportError), entao
usamos testes estruturais via AST (mesmo padrao de test_sync_graph_to_neo4j
e test_generate_video_thumbnails).
"""

import ast
from pathlib import Path

DAG_FILE = Path("src/data_platform/dags/ner_backfill.py")


def _parse() -> ast.Module:
    return ast.parse(DAG_FILE.read_text())


def _source() -> str:
    return DAG_FILE.read_text()


def test_parseia_sem_erro():
    """O modulo deve ser AST-parseavel (gate minimo de sintaxe)."""
    assert _parse() is not None


def test_airflow_protegido_por_try_except():
    """Imports do airflow/provider so existem no Composer: try/except ImportError no topo."""
    tree = _parse()
    has_guard = any(
        isinstance(node, ast.Try)
        and any(isinstance(h.type, ast.Name) and h.type.id == "ImportError" for h in node.handlers)
        for node in tree.body
    )
    assert has_guard, "imports do airflow devem estar em try/except ImportError"


def test_provider_nao_importado_fora_do_try():
    """O operador do provider nao pode ser import de topo nao-protegido (quebraria o parse)."""
    tree = _parse()
    top_level_imports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            top_level_imports.append(node.module or "")
    assert not any("cloud_run" in (m or "") for m in top_level_imports)


def test_dag_id_correto():
    assert 'dag_id="ner_backfill"' in _source()


def test_schedule_4x_dia_offset_2h():
    """Schedule 4x/dia com offset de 2h do canonicalize_backfill.

    PR #185: Schedule mudou de diário (0 4 * * *) para 4x/dia (0 2-23/6 * * *)
    Offset de 2h garante que NER roda após canon: 02:00, 08:00, 14:00, 20:00
    Canon roda em: 00:00, 06:00, 12:00, 18:00
    """
    assert 'schedule="0 2-23/6 * * *"' in _source()


def test_catchup_false_e_max_active_runs_1():
    src = _source()
    assert "catchup=False" in src
    assert "max_active_runs=1" in src


def test_retries_1():
    assert '"retries": 1' in _source()


def test_tags_corretas():
    src = _source()
    for tag in ("silver", "entities", "ner", "backfill"):
        assert f'"{tag}"' in src, f"tag {tag} ausente"


def test_usa_cloud_run_execute_job_operator():
    assert "CloudRunExecuteJobOperator(" in _source()


def test_job_name_via_variable_com_default():
    src = _source()
    assert 'Variable.get("ner_job_name"' in src
    assert "destaquesgovbr-ner-backfill" in src


def test_region_via_variable_com_default():
    src = _source()
    assert 'Variable.get("cloud_run_jobs_region"' in src
    assert "southamerica-east1" in src


def test_project_id_via_env_gcp_project_id():
    assert 'os.environ["GCP_PROJECT_ID"]' in _source()


def test_overrides_usa_container_overrides_snake_case():
    """Formato do overrides = RunJobRequest.Overrides (proto-plus snake_case)."""
    src = _source()
    assert '"container_overrides"' in src
    assert '"args"' in src


def test_args_limit_e_order_desc():
    """Valida que args --limit e --order são passados corretamente.

    Commit df5d809: Ordem mudou de 'asc' para 'desc' (newest-first por padrão).
    """
    src = _source()
    assert '"--limit"' in src
    assert '"--order"' in src
    assert 'Variable.get("ner_run_limit"' in src
    # Ordem default 'desc' (artigos mais novos primeiro)
    assert 'DEFAULT_ORDER = "desc"' in src


def test_args_passed_via_overrides():
    """Args passados via overrides.container_overrides (clear_args foi removido).

    Commit b5f5a56: clear_args e args são mutuamente exclusivos na API Cloud Run v2.
    Apenas args já substitui os args do container.
    """
    src = _source()
    # Verifica que args são passados via container_overrides
    assert '"args":' in src
    assert '--limit' in src
    assert '--order' in src
    assert '--workers' in src
    # clear_args foi removido do código (apenas aparece em comentário agora)
    assert '"clear_args"' not in src  # Não aparece como chave no dicionário


def test_instancia_dag_no_modulo():
    assert "dag_instance = ner_backfill()" in _source()
