"""O Composer recebe jobs/trend_detection como plugin copiado sozinho
(.github/workflows/composer-deploy-dags.yaml): o pacote não pode depender de
outros módulos de data_platform, que não existem no bucket de plugins."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PKG_DIR = ROOT / "src" / "data_platform" / "jobs" / "trend_detection"
WORKFLOW = ROOT / ".github" / "workflows" / "composer-deploy-dags.yaml"
PKG = "data_platform.jobs.trend_detection"


def _imported_modules(path: Path) -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


@pytest.mark.parametrize("path", sorted(PKG_DIR.glob("*.py")), ids=lambda p: p.name)
def test_nao_importa_outros_modulos_do_data_platform(path):
    for module in _imported_modules(path):
        if module.split(".")[0] == "data_platform":
            assert module.startswith(PKG), f"{path.name} importa {module}"


def test_workflow_copia_o_pacote_como_plugin():
    assert "cp -r src/data_platform/jobs/trend_detection " in WORKFLOW.read_text()
