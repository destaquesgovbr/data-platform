"""feature-worker-deploy.yaml redeploya o worker quando muda o código que ele importa (DP-1c).

O Flesch pt-BR saiu de workers/feature_worker/features.py para jobs/features/readability_ptbr.py
(para rodar também no Composer). O worker importa de lá: sem esse caminho no gatilho, um ajuste
no cálculo iria para o Composer (composer-deploy-dags) e não para o worker, e os dois escritores
de readability_flesch_ptbr divergiriam.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "feature-worker-deploy.yaml"


def _push_paths() -> list[str]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    on = workflow.get("on", workflow.get(True))  # PyYAML lê a chave `on` como True
    return on["push"]["paths"]


def test_deploy_dispara_quando_o_flesch_ptbr_compartilhado_muda():
    assert "src/data_platform/jobs/features/**" in _push_paths()


def test_deploy_continua_disparando_pelo_codigo_do_worker():
    assert "src/data_platform/workers/feature_worker/**" in _push_paths()
