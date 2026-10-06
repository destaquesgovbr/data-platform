"""Os testes de integração que usam o banco descartável de test_migrate_integration
(MIGRATION_TEST_DATABASE_URL) só rodam no CI pelo ci-migrations.yaml: o tests.yaml roda
apenas tests/unit. Cada arquivo que depende desse banco precisa estar no pytest do
workflow, e o código que ele exercita precisa estar nos paths que disparam o workflow.
Sem isso, uma regressão no SQL (dias em BRT, snapshot único do persist, seleção do B1)
passaria no CI, porque os testes unitários equivalentes usam mocks.
"""

from fnmatch import fnmatch
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci-migrations.yaml"
INTEGRATION_DIR = ROOT / "tests" / "integration"


def _disposable_db_tests() -> list[str]:
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in INTEGRATION_DIR.glob("test_*.py")
        if "MIGRATION_TEST_DATABASE_URL" in (text := path.read_text())
        or "test_migrate_integration" in text
    )


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _trigger_paths() -> list[str]:
    workflow = _workflow()
    on = workflow.get("on", workflow.get(True))  # PyYAML lê a chave `on` como True
    return on["pull_request"]["paths"]


def _pytest_args() -> list[str]:
    steps = _workflow()["jobs"]["test-migrations"]["steps"]
    (run,) = [step["run"] for step in steps if "pytest" in step.get("run", "")]
    return run.split()


def test_descobre_os_testes_do_banco_descartavel():
    assert _disposable_db_tests() == [
        "tests/integration/test_backfill_features_window_integration.py",
        "tests/integration/test_migrate_integration.py",
        "tests/integration/test_trend_detection_integration.py",
    ]


@pytest.mark.parametrize("test_file", _disposable_db_tests())
def test_pytest_do_workflow_roda_o_arquivo(test_file):
    assert test_file in _pytest_args()


@pytest.mark.parametrize("test_file", _disposable_db_tests())
def test_workflow_dispara_quando_o_teste_muda(test_file):
    assert test_file in _trigger_paths()


@pytest.mark.parametrize(
    "source",
    [
        "scripts/migrate.py",
        "scripts/migrations/029_entity_trending_baseline.sql",
        "src/data_platform/jobs/trend_detection/signals.py",
        "src/data_platform/jobs/trend_detection/persist.py",
        "scripts/backfill_features_window.py",
        "src/data_platform/workers/feature_worker/handler.py",
        ".github/workflows/ci-migrations.yaml",
    ],
)
def test_workflow_dispara_quando_o_codigo_exercitado_muda(source):
    assert any(fnmatch(source, pattern) for pattern in _trigger_paths())
