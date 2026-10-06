"""
scorer.py — função de scoring (ESTE é o arquivo que o agente modifica).

Recebe o snapshot de load_snapshot() e retorna uma lista de
(entity_id, score) ordenada do maior para o menor score.

Ponto de partida: o scorer de produção (data_platform.jobs.trend_detection.scorer),
reexportado para que a primeira rodada do evaluate.py meça exatamente o DAG.
Para experimentar (ex.: D1 — log1p(volume_ratio) e limite do agency_growth),
troque a reexportação por uma compute_scores local, partindo de uma cópia do
arquivo de produção. Ao adotar uma variante, porte-a para
src/data_platform/jobs/trend_detection/scorer.py com testes e volte à reexportação.

Sinais em data['entity_stats'][entity_id]: ver o docstring do scorer de produção
(volume_ratio com Laplace, is_new, window_active_days, agências, semantic_novelty...).
"""

import sys
from pathlib import Path

# Importa o data_platform deste checkout, e não o de um install editável de outro.
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_platform.jobs.trend_detection.scorer import compute_scores

__all__ = ["compute_scores"]
