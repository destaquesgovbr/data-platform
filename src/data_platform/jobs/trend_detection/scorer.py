"""
scorer.py — função de scoring para trend detection.

Recebe o snapshot de load_snapshot() e retorna uma lista de
(entity_id, score) ordenada do maior para o menor score.

Sinais disponíveis em data['entity_stats'][entity_id] (ver signals.load_snapshot):
  - canonical_name     str
  - entity_type        str   ORG|PER|EVENT|POLICY|LAW|LOC
  - window_count       int   artigos na janela (7 dias)
  - baseline_count     int   artigos no baseline (28 dias)
  - window_daily       float window_count / 7
  - baseline_daily     float baseline_count / 28 (sem piso: 0.0 se não houver baseline)
  - volume_ratio       float razão com Laplace ((wc+1)/W)/((bc+1)/B) — usada aqui
  - is_new             bool  baseline_count == 0
  - window_active_days int   dias distintos (America/Sao_Paulo) com menção na janela
  - window_agencies    int   agências distintas na janela
  - baseline_agencies  int   agências distintas no baseline
  - semantic_novelty   float avg(1 - cosine_sim) entre window e centroide baseline
  - new_edge_count     int   novas arestas de co-menção formadas na janela

Os pesos (0,40/0,25/0,20/0,15) foram calibrados para o vr cru. Comprimir o vr
(log1p) e limitar o agency_growth é a decisão D1, pendente do evaluate.py.
"""

# Rajadas de um único dia (ex.: cobertura concentrada de um evento) não são tendência.
MIN_WINDOW_ACTIVE_DAYS = 2


def compute_scores(data: dict) -> list[tuple[str, float]]:
    """Retorna [(entity_id, score), ...] ordenado por score DESC."""
    results = []

    for eid, s in data["entity_stats"].items():
        if s["window_count"] < 3:
            continue
        if s.get("window_active_days", 0) < MIN_WINDOW_ACTIVE_DAYS:
            continue  # burst de um dia só
        if s["entity_type"] == "LOC":
            continue  # oracle never selects LOC
        if s["window_agencies"] <= s["baseline_agencies"]:
            continue

        volume_ratio = s["volume_ratio"]  # mesmo valor do oráculo e do persist

        if volume_ratio <= 1.5:
            continue  # oracle hard condition: must have significant volume spike
        if s["baseline_agencies"] > 20:
            continue  # oracle hard condition: must be niche

        agency_growth = s["window_agencies"] / max(s["baseline_agencies"], 1)
        niche = 1.0 / (1.0 + s["baseline_agencies"])

        score = (
            0.40 * volume_ratio
            + 0.25 * agency_growth
            + 0.20 * niche * volume_ratio
            + 0.15 * s["semantic_novelty"]
        )
        results.append((eid, score))

    return sorted(results, key=lambda x: x[1], reverse=True)
