"""
evaluate.py — harness de backtesting (NÃO MODIFICAR).

Avalia scorer.compute_scores() sobre K janelas temporais deslizando
para trás no tempo. Métrica: NDCG@10 médio.

Uso: python evaluate.py > run.log 2>&1
"""

import time
from datetime import date, timedelta
from statistics import mean

import numpy as np
from sklearn.metrics import ndcg_score

from scorer import compute_scores
from signals import load_snapshot

K_EVAL_POINTS = 20   # janelas de avaliação, step = 3 dias
STEP_DAYS = 3        # dias entre pontos de avaliação


def compute_ndcg10(
    scores: list[tuple[str, float]], oracle_labels: dict[str, bool]
) -> float:
    """Calcula NDCG@10 da lista rankeada contra os oracle_labels."""
    if not scores or not any(oracle_labels.values()):
        return 0.0

    all_entities = list(
        set(list(oracle_labels.keys()) + [eid for eid, _ in scores])
    )
    score_dict = dict(scores)

    y_true = np.array(
        [[1.0 if oracle_labels.get(eid, False) else 0.0 for eid in all_entities]]
    )
    y_score = np.array([[score_dict.get(eid, 0.0) for eid in all_entities]])

    if y_true.sum() == 0:
        return 0.0

    return float(ndcg_score(y_true, y_score, k=10))


def main():
    start = time.time()
    today = date.today()

    ndcg_values = []
    oracle_positive_counts = []

    for i in range(K_EVAL_POINTS):
        date_end = today - timedelta(days=i * STEP_DAYS)
        data = load_snapshot(date_end=date_end)

        if not data["entity_stats"]:
            continue

        scores = compute_scores(data)
        ndcg = compute_ndcg10(scores, data["oracle_labels"])
        n_positives = sum(data["oracle_labels"].values())

        ndcg_values.append(ndcg)
        oracle_positive_counts.append(n_positives)

    avg_ndcg = mean(ndcg_values) if ndcg_values else 0.0
    avg_positives = mean(oracle_positive_counts) if oracle_positive_counts else 0.0
    elapsed = time.time() - start

    print("---")
    print(f"ndcg@10:          {avg_ndcg:.6f}")
    print(f"eval_points:      {len(ndcg_values)}")
    print(f"avg_oracle_pos:   {avg_positives:.1f}")
    print(f"total_seconds:    {elapsed:.1f}")


if __name__ == "__main__":
    main()
