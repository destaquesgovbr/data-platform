"""
evaluate.py — harness de backtesting (NÃO MODIFICAR).

Avalia scorer.compute_scores() sobre K janelas temporais deslizando
para trás no tempo. Métrica: NDCG@10 médio.

Cada execução é logada como uma MLflow run no experimento
"trend-detection-autoresearch" (se DGB_MLFLOW_TRACKING_URI estiver no .env).

Uso: python evaluate.py > run.log 2>&1
"""

import os
import subprocess
import time
from contextlib import nullcontext
from datetime import date, timedelta
from statistics import mean

import numpy as np
from dotenv import load_dotenv
from sklearn.metrics import ndcg_score

load_dotenv()  # carrega .env antes de qualquer config MLflow

_MLFLOW_AVAILABLE = False
_MLFLOW_URI = os.environ.get("DGB_MLFLOW_TRACKING_URI", "")

if _MLFLOW_URI:
    try:
        import mlflow
        _is_local = _MLFLOW_URI.startswith("http://localhost") or _MLFLOW_URI.startswith("http://127.")
        if _is_local:
            # Proxy local (gcloud run services proxy) — sem IAP headers, o proxy autentica por conta própria
            mlflow.set_tracking_uri(_MLFLOW_URI)
        else:
            # Servidor remoto protegido por IAP — usar dgb_mlflow para injetar Bearer token
            import dgb_mlflow
            dgb_mlflow.configure()
        _MLFLOW_AVAILABLE = True
    except Exception as _e:
        print(f"[MLflow] unavailable, skipping: {_e}", flush=True)

from scorer import compute_scores
from signals import load_snapshot

EXPERIMENT_NAME = "trend-detection-autoresearch"
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


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def main():
    start = time.time()
    today = date.today()

    _mlflow_active = False
    if _MLFLOW_AVAILABLE:
        try:
            mlflow.set_experiment(EXPERIMENT_NAME)
            _mlflow_active = True
        except Exception as _e:
            print(f"[MLflow] set_experiment failed, skipping: {_e}", flush=True)

    run_ctx = mlflow.start_run() if _mlflow_active else nullcontext()

    with run_ctx:
        if _mlflow_active:
            mlflow.log_params({
                "k_eval_points": K_EVAL_POINTS,
                "step_days": STEP_DAYS,
                "window_days": 7,
                "baseline_days": 28,
            })
            mlflow.set_tag("git_commit", _git_commit_hash())

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

        if _mlflow_active:
            mlflow.log_metrics({
                "ndcg_at_10": avg_ndcg,
                "eval_points": float(len(ndcg_values)),
                "avg_oracle_positives": avg_positives,
                "total_seconds": elapsed,
            })
            try:
                mlflow.log_artifact("scorer.py")
            except Exception:
                pass

    print("---")
    print(f"ndcg@10:          {avg_ndcg:.6f}")
    print(f"eval_points:      {len(ndcg_values)}")
    print(f"avg_oracle_pos:   {avg_positives:.1f}")
    print(f"total_seconds:    {elapsed:.1f}")


if __name__ == "__main__":
    main()
