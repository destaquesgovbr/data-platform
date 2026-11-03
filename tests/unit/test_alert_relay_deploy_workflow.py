"""alert-relay-deploy.yaml aponta para os recursos criados no infra (ops-alerts.tf)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "alert-relay-deploy.yaml"
DOCKERFILE = ROOT / "docker" / "alert-relay" / "Dockerfile"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_deploy_dispara_pelo_codigo_do_relay():
    on = _workflow().get("on", _workflow().get(True))  # PyYAML lê `on` como True
    assert "src/data_platform/workers/alert_relay/**" in on["push"]["paths"]


def test_deploy_usa_servico_e_repositorio_do_infra():
    params = _workflow()["jobs"]["deploy"]["with"]
    assert params["cloud_run_service"] == "destaquesgovbr-alert-relay"
    assert params["ar_repository"] == "destaquesgovbr-alert-relay"
    assert params["dockerfile"] == "docker/alert-relay/Dockerfile"


def test_dockerfile_sobe_o_app_do_relay():
    assert "data_platform.workers.alert_relay.app:app" in DOCKERFILE.read_text()
