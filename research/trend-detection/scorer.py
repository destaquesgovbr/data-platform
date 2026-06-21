"""
scorer.py — função de scoring (ESTE é o arquivo que o agente modifica).

Recebe o snapshot de load_snapshot() e retorna uma lista de
(entity_id, score) ordenada do maior para o menor score.

Sinais disponíveis em data['entity_stats'][entity_id]:
  - canonical_name    str
  - entity_type       str   ORG|PER|EVENT|POLICY|LAW|LOC
  - window_count      int   artigos na janela (7 dias)
  - baseline_count    int   artigos no baseline (28 dias anteriores)
  - window_daily      float window_count / 7
  - baseline_daily    float baseline_count / 28 (mín 0.001)
  - window_agencies   int   agências distintas na janela
  - baseline_agencies int   agências distintas no baseline
  - semantic_novelty  float avg(1 - cosine_sim) entre window e centroide baseline
  - new_edge_count    int   novas arestas de co-menção formadas na janela
"""

import math


def compute_scores(data: dict) -> list[tuple[str, float]]:
    """Retorna [(entity_id, score), ...] ordenado por score DESC."""
    results = []

    for eid, s in data["entity_stats"].items():
        if s["window_count"] < 3:
            continue

        volume_ratio = s["window_daily"] / s["baseline_daily"]
        agency_growth = s["window_agencies"] / max(s["baseline_agencies"], 1)

        score = math.log1p(volume_ratio) * agency_growth
        results.append((eid, score))

    return sorted(results, key=lambda x: x[1], reverse=True)
