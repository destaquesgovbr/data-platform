"""signals.py — carregamento de snapshot de entidades NER para trend detection.

Este pacote é copiado sozinho como plugin do Cloud Composer
(composer-deploy-dags.yaml): não importe outros módulos de data_platform aqui.
"""

from collections.abc import Iterable
from datetime import date, timedelta

import numpy as np
import psycopg2

TREND_DETECTION_VERSION = "trend_detection v2 (laplace, snapshot)"

# Defeso eleitoral de 2026 (inclusive nas duas pontas, com o 2º turno).
BLACKOUT_FIRST_DAY = date(2026, 7, 4)
BLACKOUT_LAST_DAY = date(2026, 10, 25)

# Limiar de volume do oráculo (e do scorer): volume_ratio (Laplace) > 1,5.
VOLUME_RATIO_THRESHOLD = 1.5


def _cosine_sim_batch(vecs: np.ndarray, centroid: np.ndarray) -> np.ndarray:
    """Cosine similarity between each row in vecs and centroid."""
    norms = np.linalg.norm(vecs, axis=1)
    norm_c = np.linalg.norm(centroid)
    if norm_c < 1e-9:
        return np.zeros(len(vecs))
    valid = norms > 1e-9
    sims = np.zeros(len(vecs))
    sims[valid] = (vecs[valid] @ centroid) / (norms[valid] * norm_c)
    return sims


def laplace_volume_ratio(
    window_count: int, baseline_count: int, window_days: int, baseline_days: int
) -> float:
    """Razão entre as médias diárias da janela e do baseline, com suavização de Laplace.

    ((wc + 1) / W) / ((bc + 1) / B). Sempre finita e positiva, inclusive com bc = 0
    (substitui o piso baseline_daily = 0,001, que gerava razões da ordem de 8000×).
    """
    return ((window_count + 1) / window_days) / ((baseline_count + 1) / baseline_days)


def resolve_baseline_window(
    date_end: date, window_days: int = 7, baseline_days: int = 28
) -> tuple[date, date]:
    """Devolve o baseline [início, fim) a usar para a janela que termina em date_end.

    Decisão D2 (Fase 2.5): na retomada pós-defeso o baseline rolante cairia todo
    dentro do defeso (volume ~35% menor e ~39 agências mudas), gerando baseline zero
    em massa. Enquanto o baseline rolante tocar o defeso — de BLACKOUT_LAST_DAY + 1
    (26/10) até BLACKOUT_LAST_DAY + W + B (29/11), inclusive — usa-se os B dias
    imediatamente anteriores ao defeso ([06/06, 04/07) com B = 28). Fora disso,
    o baseline rolante [date_end - W - B, date_end - W).

    Durante o override, is_new passa a significar "não visto no pré-defeso".
    """
    recovery_start = BLACKOUT_LAST_DAY + timedelta(days=1)
    recovery_end = BLACKOUT_LAST_DAY + timedelta(days=1 + window_days + baseline_days)
    if recovery_start <= date_end < recovery_end:
        return BLACKOUT_FIRST_DAY - timedelta(days=baseline_days), BLACKOUT_FIRST_DAY
    window_start = date_end - timedelta(days=window_days)
    return window_start - timedelta(days=baseline_days), window_start


def build_entity_stats(rows: Iterable[tuple], window_days: int, baseline_days: int) -> dict:
    """Monta entity_stats a partir das linhas do SELECT de load_snapshot.

    Cada linha: (entity_id, canonical_name, entity_type, window_count, baseline_count,
    window_agencies, baseline_agencies, window_active_days).
    """
    entity_stats: dict = {}
    for eid, cname, etype, wc, bc, wa, ba, active_days in rows:
        entity_stats[eid] = {
            "canonical_name": cname,
            "entity_type": etype,
            "window_count": wc,
            "baseline_count": bc,
            "window_daily": wc / window_days,
            "baseline_daily": bc / baseline_days,
            "volume_ratio": laplace_volume_ratio(wc, bc, window_days, baseline_days),
            "is_new": bc == 0,
            "window_active_days": active_days,
            "window_agencies": wa,
            "baseline_agencies": ba,
            "semantic_novelty": 0.0,
            "new_edge_count": 0,
        }
    return entity_stats


def build_oracle_labels(entity_stats: dict, min_window_articles: int) -> dict[str, bool]:
    """Rótulos do oráculo (filtros hard), com o mesmo volume_ratio do snapshot."""
    oracle_labels: dict[str, bool] = {}
    for eid, s in entity_stats.items():
        if s["entity_type"] == "LOC":
            oracle_labels[eid] = False
            continue
        oracle_labels[eid] = bool(
            s["window_agencies"] > s["baseline_agencies"]
            and s["volume_ratio"] > VOLUME_RATIO_THRESHOLD
            and s["window_count"] >= min_window_articles
            and s["baseline_agencies"] <= 20
        )
    return oracle_labels


def load_snapshot(
    db_url: str,
    window_days: int = 7,
    baseline_days: int = 28,
    date_end: date | None = None,
    min_window_articles: int = 3,
    compute_embeddings: bool = False,
    baseline_start: date | None = None,
    baseline_end: date | None = None,
) -> dict:
    """
    Retorna dict com entity_stats e oracle_labels para uma janela temporal.

    Janela: [date_end - window_days, date_end). Baseline: [baseline_start, baseline_end)
    se informado (override, ver resolve_baseline_window); senão o rolante
    [date_end - window_days - baseline_days, date_end - window_days). Com override,
    a duração efetiva do baseline (baseline_end - baseline_start) entra nas médias.

    entity_stats[entity_id] = {
        'canonical_name': str,
        'entity_type': str,          # ORG|PER|EVENT|POLICY|LAW|LOC
        'window_count': int,
        'baseline_count': int,
        'window_daily': float,       # window_count / W
        'baseline_daily': float,     # baseline_count / B (sem piso; 0.0 se bc = 0)
        'volume_ratio': float,       # laplace_volume_ratio(wc, bc, W, B)
        'is_new': bool,              # baseline_count == 0
        'window_active_days': int,   # dias distintos (America/Sao_Paulo) com menção
        'window_agencies': int,
        'baseline_agencies': int,
        'semantic_novelty': float,
        'new_edge_count': int,
    }
    oracle_labels[entity_id] = True | False
    """
    if date_end is None:
        date_end = date.today()

    window_start = date_end - timedelta(days=window_days)
    if (baseline_start is None) != (baseline_end is None):
        raise ValueError("baseline_start e baseline_end devem ser informados juntos")
    if baseline_start is None or baseline_end is None:
        baseline_end = window_start
        baseline_start = window_start - timedelta(days=baseline_days)
    if not baseline_start < baseline_end <= window_start:
        raise ValueError(
            f"baseline [{baseline_start}, {baseline_end}) inválido para a janela "
            f"[{window_start}, {date_end})"
        )
    effective_baseline_days = (baseline_end - baseline_start).days

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH window_stats AS (
                    SELECT
                        ne.entity_id,
                        COUNT(DISTINCT ne.unique_id)   AS window_count,
                        COUNT(DISTINCT n.agency_key)   AS window_agencies,
                        COUNT(DISTINCT
                            (ne.published_at AT TIME ZONE 'America/Sao_Paulo')::date
                        )                              AS window_active_days
                    FROM news_entities ne
                    JOIN news n USING (unique_id)
                    WHERE ne.published_at >= %(window_start)s
                      AND ne.published_at <  %(date_end)s
                    GROUP BY ne.entity_id
                ),
                baseline_stats AS (
                    SELECT
                        ne.entity_id,
                        COUNT(DISTINCT ne.unique_id)   AS baseline_count,
                        COUNT(DISTINCT n.agency_key)   AS baseline_agencies
                    FROM news_entities ne
                    JOIN news n USING (unique_id)
                    WHERE ne.published_at >= %(baseline_start)s
                      AND ne.published_at <  %(baseline_end)s
                    GROUP BY ne.entity_id
                )
                SELECT
                    er.entity_id,
                    er.canonical_name,
                    er.type                           AS entity_type,
                    COALESCE(w.window_count,     0)   AS window_count,
                    COALESCE(b.baseline_count,   0)   AS baseline_count,
                    COALESCE(w.window_agencies,  0)   AS window_agencies,
                    COALESCE(b.baseline_agencies, 0)  AS baseline_agencies,
                    w.window_active_days
                FROM entity_registry er
                INNER JOIN window_stats   w USING (entity_id)
                LEFT  JOIN baseline_stats b USING (entity_id)
                WHERE w.window_count >= %(min_window_articles)s
                """,
                {
                    "window_start": window_start,
                    "date_end": date_end,
                    "baseline_start": baseline_start,
                    "baseline_end": baseline_end,
                    "min_window_articles": min_window_articles,
                },
            )
            rows = cur.fetchall()

        if not rows:
            return {"entity_stats": {}, "oracle_labels": {}}

        entity_ids = [r[0] for r in rows]
        entity_stats = build_entity_stats(rows, window_days, effective_baseline_days)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_id, SUM(cnt) AS new_edge_count
                FROM (
                    SELECT src_id AS entity_id, COUNT(*) AS cnt
                    FROM entity_edges
                    WHERE kind = 'co_mention'
                      AND first_seen >= %(window_start)s
                      AND first_seen <  %(date_end)s
                      AND src_id = ANY(%(entity_ids)s)
                    GROUP BY src_id
                    UNION ALL
                    SELECT dst_id AS entity_id, COUNT(*) AS cnt
                    FROM entity_edges
                    WHERE kind = 'co_mention'
                      AND first_seen >= %(window_start)s
                      AND first_seen <  %(date_end)s
                      AND dst_id = ANY(%(entity_ids)s)
                    GROUP BY dst_id
                ) sub
                GROUP BY entity_id
                """,
                {
                    "window_start": window_start,
                    "date_end": date_end,
                    "entity_ids": entity_ids,
                },
            )
            for eid, cnt in cur.fetchall():
                if eid in entity_stats:
                    entity_stats[eid]["new_edge_count"] = int(cnt)

        if compute_embeddings:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ne.entity_id, n.content_embedding::float4[] AS embedding
                    FROM news_entities ne
                    JOIN news n USING (unique_id)
                    WHERE ne.published_at >= %(baseline_start)s
                      AND ne.published_at <  %(baseline_end)s
                      AND n.content_embedding IS NOT NULL
                      AND ne.entity_id = ANY(%(entity_ids)s)
                    """,
                    {
                        "baseline_start": baseline_start,
                        "baseline_end": baseline_end,
                        "entity_ids": entity_ids,
                    },
                )
                baseline_embs: dict[str, list] = {}
                for eid, emb in cur.fetchall():
                    baseline_embs.setdefault(eid, []).append(emb)

            centroids: dict[str, np.ndarray] = {}
            for eid, embs in baseline_embs.items():
                arr = np.array(embs, dtype=np.float32)
                centroids[eid] = arr.mean(axis=0)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ne.entity_id, n.content_embedding::float4[] AS embedding
                    FROM news_entities ne
                    JOIN news n USING (unique_id)
                    WHERE ne.published_at >= %(window_start)s
                      AND ne.published_at <  %(date_end)s
                      AND n.content_embedding IS NOT NULL
                      AND ne.entity_id = ANY(%(entity_ids)s)
                    """,
                    {
                        "window_start": window_start,
                        "date_end": date_end,
                        "entity_ids": entity_ids,
                    },
                )
                window_embs: dict[str, list] = {}
                for eid, emb in cur.fetchall():
                    window_embs.setdefault(eid, []).append(emb)

            for eid, embs in window_embs.items():
                if eid not in centroids or eid not in entity_stats:
                    continue
                arr = np.array(embs, dtype=np.float32)
                sims = _cosine_sim_batch(arr, centroids[eid])
                entity_stats[eid]["semantic_novelty"] = float(1.0 - sims.mean())

        oracle_labels = build_oracle_labels(entity_stats, min_window_articles)

        return {"entity_stats": entity_stats, "oracle_labels": oracle_labels}

    finally:
        conn.close()
