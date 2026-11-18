"""composer-deploy-dags.yaml publica DAGs e plugins no Composer e no Airflow próprio (Fase 3).

O Composer não tem pyphen nos pacotes PyPI do ambiente (gerenciados pelo Terraform). O deploy
instala o pyphen da versão travada no poetry.lock (a mesma do feature-worker) na raiz dos
plugins, que está no sys.path dos workers, e copia jobs/features para data_platform/jobs
(DP-1c).

Na Fase 3 da migração do Composer os plugins vão para os dois buckets (AIRFLOW_DAG_BUCKETS),
sem `gcloud composer describe`, e as DAGs pelo airflow-deploy-dags.yml@v3, que recebe a mesma
lista (output do job de plugins). Plugins antes das DAGs, que os importam, e só depois de um
py_compile das DAGs e dos plugins; um deploy por vez.
"""

import os
import re
import shutil
import subprocess
import sys
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


GATE = "Validar sintaxe das DAGs e dos plugins (py_compile)"


def _bash(script: str, cwd: Path, **env: str) -> subprocess.CompletedProcess:
    """Roda um `run:` como o Actions (bash -e), com `python` = o interpretador dos testes."""
    script = re.sub(r"\bpython -m\b", f'"{sys.executable}" -m', script)
    return subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


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
    """Fase 7 (desligar o Composer) tira o bucket do Composer daqui (plugins e DAGs)."""
    assert _workflow()["env"]["AIRFLOW_DAG_BUCKETS"].split() == [COMPOSER_BUCKET, AIRFLOW_BUCKET]


def test_plugins_vao_para_cada_bucket_com_rsync_que_apaga_orfaos():
    run = _deploy_run()
    assert "for bucket in ${AIRFLOW_DAG_BUCKETS}; do" in run
    assert run.count(RSYNC) == 2
    assert f'{RSYNC} /tmp/plugins/data_platform/ "gs://${{bucket}}/plugins/data_platform/"' in run
    assert f'{RSYNC} /tmp/plugins_vendor/pyphen/ "gs://${{bucket}}/plugins/pyphen/"' in run


def test_falha_se_a_lista_de_buckets_estiver_vazia(tmp_path):
    """Sem a guarda o laço não roda e o job fica verde sem publicar nada."""
    run = _plugin_steps()["Conferir buckets"]
    saida = tmp_path / "github_output"

    result = _bash(run, tmp_path, AIRFLOW_DAG_BUCKETS="  ", GITHUB_OUTPUT=str(saida))

    assert result.returncode != 0
    assert not saida.exists()


def test_repassa_a_lista_de_buckets_como_output(tmp_path):
    run = _plugin_steps()["Conferir buckets"]
    saida = tmp_path / "github_output"
    buckets = _workflow()["env"]["AIRFLOW_DAG_BUCKETS"]

    result = _bash(run, tmp_path, AIRFLOW_DAG_BUCKETS=buckets, GITHUB_OUTPUT=str(saida))

    assert result.returncode == 0, result.stderr
    assert saida.read_text() == f"buckets={buckets}\n"
    job = _workflow()["jobs"]["deploy-plugins"]
    assert job["outputs"] == {"buckets": "${{ steps.buckets.outputs.buckets }}"}
    assert job["steps"][0]["id"] == "buckets"


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
    # Mesma lista dos plugins (o contexto env não chega ao `with:`): o default de `buckets` do
    # v3 não vale aqui, e a Fase 7 só mexe em AIRFLOW_DAG_BUCKETS.
    assert dags["with"] == {
        "dags_local_path": "src/data_platform/dags",
        "dags_bucket_subdir": "data-platform",
        "buckets": "${{ needs.deploy-plugins.outputs.buckets }}",
    }
    assert "needs" not in jobs["deploy-plugins"]


def test_um_deploy_por_vez_sem_cancelar_o_que_esta_rodando():
    """Plugins de um run e DAGs de outro não se misturam (os dois rsync apagam no destino)."""
    concurrency = _workflow()["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    # O grupo do job de deploy do v3 é airflow-deploy-dags-<repo>-<subpasta>: o mesmo nome no
    # nível do workflow seria um deadlock.
    assert not concurrency["group"].startswith("airflow-deploy-dags-")
    assert "${{" not in concurrency["group"]


def test_valida_a_sintaxe_com_python_3_11_antes_de_publicar():
    steps = _workflow()["jobs"]["deploy-plugins"]["steps"]
    nomes = [step.get("name") or step.get("uses") for step in steps]
    setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python"))
    assert setup["with"]["python-version"] == "3.11"
    assert nomes.index(setup["uses"]) < nomes.index(GATE)
    assert nomes.index("Prepare plugins directory") < nomes.index(GATE)
    assert nomes.index(GATE) < nomes.index("Deploy plugins to GCS")
    gate = next(step for step in steps if step.get("name") == GATE)
    # .pyc fora de /tmp/plugins, que é publicado com rsync.
    assert gate["env"]["PYTHONPYCACHEPREFIX"] == "${{ runner.temp }}/pycache"


def _monta_plugins(tmp_path: Path) -> tuple[str, dict[str, str]]:
    """Roda o "Prepare plugins directory" com /tmp/plugins trocado por tmp_path/plugins."""
    plugins = tmp_path / "plugins"
    prepare = _plugin_steps()["Prepare plugins directory"].replace("/tmp/plugins", str(plugins))
    result = _bash(prepare, ROOT)
    assert result.returncode == 0, result.stderr
    # O checkout do Actions não tem __pycache__; o src/ local (e o do CI, depois dos testes) tem.
    for cache in sorted(plugins.rglob("__pycache__"), reverse=True):
        shutil.rmtree(cache)
    gate = _plugin_steps()[GATE].replace("/tmp/plugins", str(plugins))
    return gate, {"PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")}


def test_py_compile_passa_nas_dags_e_plugins_atuais(tmp_path):
    gate, env = _monta_plugins(tmp_path)

    result = _bash(gate, ROOT, **env)

    assert result.returncode == 0, result.stderr
    assert not list((tmp_path / "plugins").rglob("__pycache__"))


def test_py_compile_barra_erro_de_sintaxe_nos_plugins(tmp_path):
    gate, env = _monta_plugins(tmp_path)
    (tmp_path / "plugins" / "data_platform" / "jobs" / "quebrado.py").write_text("def f(:\n")

    result = _bash(gate, ROOT, **env)

    assert result.returncode != 0
    assert "quebrado.py" in result.stdout + result.stderr


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
