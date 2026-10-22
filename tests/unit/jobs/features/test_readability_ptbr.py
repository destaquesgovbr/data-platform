"""Flesch pt-BR num módulo próprio (DP-1c), importável no Composer.

O Composer não tem textstat: a tarefa diária que completa readability_flesch_ptbr
(aggregate_engagement) importa só data_platform.jobs.features.readability_ptbr, que depende
apenas do pyphen (instalado nos plugins pelo composer-deploy-dags). O feature-worker e a 033
continuam importando de features.py, que reexporta os mesmos objetos: um único cálculo.
"""

import subprocess
import sys
from pathlib import Path

from data_platform.jobs.features import readability_ptbr
from data_platform.workers.feature_worker import features

ROOT = Path(__file__).resolve().parents[4]


def test_features_reexporta_o_mesmo_calculo():
    assert features.compute_readability_flesch_ptbr is readability_ptbr.compute_readability_flesch_ptbr
    assert features.readability_counts_ptbr is readability_ptbr.readability_counts_ptbr
    assert features.count_syllables_ptbr is readability_ptbr.count_syllables_ptbr


def test_importa_sem_textstat():
    """No Composer só há o pyphen: o módulo não pode puxar textstat (nem o feature-worker)."""
    code = (
        "import sys; sys.modules['textstat'] = None\n"
        "from data_platform.jobs.features.readability_ptbr import "
        "compute_readability_flesch_ptbr as f\n"
        "assert 'data_platform.workers.feature_worker.features' not in sys.modules\n"
        "print(f('O governo federal anunciou hoje um novo programa de apoio aos estudantes.'))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": f"{ROOT / 'src'}"},
        check=True,
    )
    assert float(out.stdout.strip()) == features.compute_readability_flesch_ptbr(
        "O governo federal anunciou hoje um novo programa de apoio aos estudantes."
    )


def test_valores_congelados_continuam():
    frase = (
        "O Ministério da Educação anunciou nesta segunda-feira um novo programa nacional de "
        "apoio aos estudantes do ensino médio em todas as regiões do país."
    )
    assert readability_ptbr.compute_readability_flesch_ptbr(frase) == (
        features.compute_readability_flesch_ptbr(frase)
    )
    assert readability_ptbr.compute_readability_flesch_ptbr("Curto demais") is None
