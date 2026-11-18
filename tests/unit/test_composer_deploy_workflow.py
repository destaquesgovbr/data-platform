"""composer-deploy-dags.yaml publica DAGs e plugins no Composer e no Airflow próprio (Fase 3).

O Composer não tem pyphen nos pacotes PyPI do ambiente (gerenciados pelo Terraform). O deploy
instala o pyphen da versão travada no poetry.lock (a mesma do feature-worker) na raiz dos
plugins, que está no sys.path dos workers, e copia jobs/features para data_platform/jobs
(DP-1c).

Na Fase 3 da migração do Composer os plugins vão para os dois buckets (AIRFLOW_DAG_BUCKETS),
sem `gcloud composer describe`, e as DAGs pelo airflow-deploy-dags.yml@v3, cujo default de
`buckets` lista os mesmos dois. Plugins antes das DAGs, que os importam.
"""

import re
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pyphen
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "composer-deploy-dags.yaml"

COMPOSER_BUCKET = "southamerica-east1-destaque-227e22da-bucket"
AIRFLOW_BUCKET = "destaquesgovbr-airflow"
RSYNC = "gcloud storage rsync --recursive --delete-unmatched-destination-objects"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _plugin_steps() -> dict[str, str]:
    steps = _workflow()["jobs"]["deploy-plugins"]["steps"]
    return {step["name"]: step.get("run", "") for step in steps if "name" in step}


def _deploy_run() -> str:
    """O passo de publicação com as continuações de linha (`\\` + quebra) juntadas."""
    return re.sub(r"\\\n\s*", "", _plugin_steps()["Deploy plugins to GCS"])


def _trigger_paths() -> list[str]:
    workflow = _workflow()
    on = workflow.get("on", workflow.get(True))  # PyYAML lê a chave `on` como True
    return on["push"]["paths"]


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
    assert '/tmp/plugins_vendor/pyphen/ "gs://${bucket}/plugins/pyphen/"' in _deploy_run()


def test_versao_do_lock_e_a_mesma_dos_testes():
    """Os valores congelados do Flesch pt-BR dependem do dicionário dessa versão."""
    assert _lock_version("pyphen") == pyphen.__version__


def test_deploy_dispara_quando_o_lock_muda():
    assert "poetry.lock" in _trigger_paths()


# --- Fase 3: dois buckets ---------------------------------------------------------------


def test_buckets_sao_o_do_composer_e_o_do_airflow_proprio():
    """Fase 7 (desligar o Composer) tira o bucket do Composer daqui e do default do v3."""
    assert _workflow()["env"]["AIRFLOW_DAG_BUCKETS"].split() == [COMPOSER_BUCKET, AIRFLOW_BUCKET]


def test_plugins_vao_para_cada_bucket_com_rsync_que_apaga_orfaos():
    run = _deploy_run()
    assert "for bucket in ${AIRFLOW_DAG_BUCKETS}; do" in run
    assert run.count(RSYNC) == 2
    assert f'{RSYNC} /tmp/plugins/data_platform/ "gs://${{bucket}}/plugins/data_platform/"' in run
    assert f'{RSYNC} /tmp/plugins_vendor/pyphen/ "gs://${{bucket}}/plugins/pyphen/"' in run


def test_falha_se_a_lista_de_buckets_estiver_vazia():
    """Sem a guarda o laço não roda e o job fica verde sem publicar nada."""
    assert _deploy_run().startswith('test -n "${AIRFLOW_DAG_BUCKETS// /}"')


def test_nao_depende_mais_do_gcloud_composer():
    """O bucket do Composer é fixo; describe exigia composer.admin, que sai na Fase 7."""
    workflow = _workflow()
    assert not [k for k in workflow["env"] if k.startswith("COMPOSER_")]
    assert not [run for run in _plugin_steps().values() if "gcloud composer" in run]
    assert "gsutil" not in WORKFLOW.read_text()


def test_dags_usam_o_reusable_v3_depois_dos_plugins():
    jobs = _workflow()["jobs"]
    dags = jobs["deploy-dags"]
    assert dags["uses"] == (
        "destaquesgovbr/reusable-workflows/.github/workflows/airflow-deploy-dags.yml@v3"
    )
    assert dags["needs"] == "deploy-plugins"
    # `buckets` fica no default do v3 (os mesmos dois); o contexto env não chega ao `with:`.
    assert dags["with"] == {
        "dags_local_path": "src/data_platform/dags",
        "dags_bucket_subdir": "data-platform",
    }
    assert "needs" not in jobs["deploy-plugins"]


def test_deploy_dispara_quando_muda_algo_copiado_para_os_plugins():
    """Antes typesense/ e cloud_run.py iam para os plugins sem disparar o deploy."""
    run = _plugin_steps()["Prepare plugins directory"]
    sources = re.findall(r"^cp (?:-r )?(src/\S+) ", run, flags=re.MULTILINE)
    assert "src/data_platform/cloud_run.py" in sources
    assert "src/data_platform/typesense/client.py" in sources
    for source in sources:
        probe = source if source.endswith(".py") else f"{source}/modulo.py"
        assert any(fnmatch(probe, p) for p in _trigger_paths()), source


def test_deploy_dispara_quando_o_proprio_workflow_muda():
    assert ".github/workflows/composer-deploy-dags.yaml" in _trigger_paths()
