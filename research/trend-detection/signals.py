"""
signals.py — carregamento de dados e oracle (NÃO MODIFICAR durante o loop).

Delega para data_platform.jobs.trend_detection.signals, o mesmo código do DAG
compute_entity_trending, para que o NDCG do evaluate.py meça o modelo de produção
(pré-requisito da decisão D1): volume_ratio com Laplace, window_active_days em
America/Sao_Paulo, baseline de resolve_baseline_window (D2) e o mesmo oráculo.

Oracle (build_oracle_labels): uma entidade é "trending" se:
  - entity_type != 'LOC'  (LOC excluído — muito ruído geográfico)
  - volume_ratio > 1.5  (Laplace: ((wc+1)/W) / ((bc+1)/B))
  - window_agencies > baseline_agencies  (expansão inter-agência)
  - window_count >= min_window_articles
  - baseline_agencies <= 20  (excluir "permanentes": Brasil, Brasília, Lula, etc.)
"""

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Importa o data_platform deste checkout, e não o de um install editável de outro.
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_platform.jobs.trend_detection import signals as _prod

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def load_snapshot(
    window_days: int = 7,
    baseline_days: int = 28,
    date_end: date | None = None,
    min_window_articles: int = 3,
    compute_embeddings: bool = False,
) -> dict:
    """
    Retorna o snapshot que o DAG computaria em date_end: entity_stats e oracle_labels.

    O baseline vem de resolve_baseline_window (rolante, ou o pré-defeso de 26/10 a
    29/11/2026). compute_embeddings=False, como no DAG, deixa semantic_novelty = 0.0;
    True calcula a novidade semântica (consultas pesadas de embeddings).

    Campos de entity_stats: ver data_platform.jobs.trend_detection.signals.load_snapshot.
    """
    if date_end is None:
        date_end = date.today()

    baseline_start, baseline_end = _prod.resolve_baseline_window(
        date_end, window_days, baseline_days
    )
    return _prod.load_snapshot(
        DATABASE_URL,
        window_days=window_days,
        baseline_days=baseline_days,
        date_end=date_end,
        min_window_articles=min_window_articles,
        compute_embeddings=compute_embeddings,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )
