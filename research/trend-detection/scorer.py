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

def compute_scores(data: dict) -> list[tuple[str, float]]:
    """Retorna [(entity_id, score), ...] ordenado por score DESC."""
    results = []

    for eid, s in data["entity_stats"].items():
        if s["window_count"] < 3:
            continue
        if s["entity_type"] == "LOC":
            continue  # oracle never selects LOC
        # oracle requires agency spread to grow: skip if no new agencies covered
        if s["window_agencies"] <= s["baseline_agencies"]:
            continue

        volume_ratio = s["window_daily"] / s["baseline_daily"]
        agency_growth = s["window_agencies"] / max(s["baseline_agencies"], 1)
        # niche bonus: entities known to fewer agencies in baseline score higher
        niche = 1.0 / (1.0 + s["baseline_agencies"])

        score = (
            0.4 * volume_ratio
            + 0.25 * agency_growth
            + 0.2 * niche * volume_ratio
            + 0.15 * s["semantic_novelty"]
        )
        results.append((eid, score))

    return sorted(results, key=lambda x: x[1], reverse=True)
