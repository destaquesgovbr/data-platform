"""composer-deploy-dags.yaml publica o que a task fill_flesch_ptbr importa no Composer (DP-1c).

O Composer não tem pyphen nos pacotes PyPI do ambiente (gerenciados pelo Terraform). O deploy
instala o pyphen da versão travada no poetry.lock (a mesma do feature-worker) na raiz dos
plugins, que está no sys.path dos workers, e copia jobs/features para data_platform/jobs.
"""

import re
import tomllib
from pathlib import Path

import pyphen
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "composer-deploy-dags.yaml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _plugin_steps() -> dict[str, str]:
    steps = _workflow()["jobs"]["deploy-plugins"]["steps"]
    return {step["name"]: step.get("run", "") for step in steps if "name" in step}


def _lock_version(name: str) -> str:
    lock = tomllib.loads((ROOT / "poetry.lock").read_text())
    return next(p["version"] for p in lock["package"] if p["name"] == name)


def test_copia_jobs_features_para_os_plugins():
    run = _plugin_steps()["Prepare plugins directory"]
    assert "cp -r src/data_platform/jobs/features /tmp/plugins/data_platform/jobs/" in run


def test_instala_o_pyphen_travado_no_lock_na_raiz_dos_plugins():
    run = _plugin_steps()["Vendor pyphen into plugins"]
    assert "poetry.lock" in run
    assert re.search(r"pip install --no-deps --target /tmp/plugins_vendor \"pyphen==", run)


def test_publica_o_pyphen_em_plugins_pyphen():
    run = _plugin_steps()["Deploy plugins to GCS"]
    assert "/tmp/plugins_vendor/pyphen/" in run
    assert "plugins_bucket }}/pyphen/" in run


def test_versao_do_lock_e_a_mesma_dos_testes():
    """Os valores congelados do Flesch pt-BR dependem do dicionário dessa versão."""
    assert _lock_version("pyphen") == pyphen.__version__


def test_deploy_dispara_quando_o_lock_muda():
    workflow = _workflow()
    on = workflow.get("on", workflow.get(True))  # PyYAML lê a chave `on` como True
    assert "poetry.lock" in on["push"]["paths"]
