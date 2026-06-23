"""signals.py — carregamento de snapshot de entidades NER para trend detection."""

from datetime import date, timedelta

import numpy as np
import psycopg2


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


def load_snapshot(
    db_url: str,
    window_days: int = 7,
    baseline_days: int = 28,
    date_end: date | None = None,
    min_window_articles: int = 3,
) -> dict:
    """
    Retorna dict com entity_stats e oracle_labels para uma janela temporal.

    entity_stats[entity_id] = {
        'canonical_name': str,
        'entity_type': str,          # ORG|PER|EVENT|POLICY|LAW|LOC
        'window_count': int,
        'baseline_count': int,
        'window_daily': float,
        'baseline_daily': float,
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
    baseline_start = date_end - timedelta(days=window_days + baseline_days)

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH window_stats AS (
                    SELECT
                        ne.entity_id,
                        COUNT(DISTINCT ne.unique_id)   AS window_count,
                        COUNT(DISTINCT n.agency_key)   AS window_agencies
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
                      AND ne.published_at <  %(window_start)s
                    GROUP BY ne.entity_id
                )
                SELECT
                    er.entity_id,
                    er.canonical_name,
                    er.type                           AS entity_type,
                    COALESCE(w.window_count,     0)   AS window_count,
                    COALESCE(b.baseline_count,   0)   AS baseline_count,
                    COALESCE(w.window_agencies,  0)   AS window_agencies,
                    COALESCE(b.baseline_agencies, 0)  AS baseline_agencies
                FROM entity_registry er
                INNER JOIN window_stats   w USING (entity_id)
                LEFT  JOIN baseline_stats b USING (entity_id)
                WHERE w.window_count >= %(min_window_articles)s
                """,
                {
                    "window_start": window_start,
                    "date_end": date_end,
                    "baseline_start": baseline_start,
                    "min_window_articles": min_window_articles,
                },
            )
            rows = cur.fetchall()

        if not rows:
            return {"entity_stats": {}, "oracle_labels": {}}

        entity_ids = [r[0] for r in rows]
        entity_stats: dict = {}
        for eid, cname, etype, wc, bc, wa, ba in rows:
            entity_stats[eid] = {
                "canonical_name": cname,
                "entity_type": etype,
                "window_count": wc,
                "baseline_count": bc,
                "window_daily": wc / window_days,
                "baseline_daily": bc / baseline_days if bc > 0 else 0.001,
                "window_agencies": wa,
                "baseline_agencies": ba,
                "semantic_novelty": 0.0,
                "new_edge_count": 0,
            }

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

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ne.entity_id, n.content_embedding::float4[] AS embedding
                FROM news_entities ne
                JOIN news n USING (unique_id)
                WHERE ne.published_at >= %(baseline_start)s
                  AND ne.published_at <  %(window_start)s
                  AND n.content_embedding IS NOT NULL
                  AND ne.entity_id = ANY(%(entity_ids)s)
                """,
                {
                    "baseline_start": baseline_start,
                    "window_start": window_start,
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

        oracle_labels: dict[str, bool] = {}
        for eid, s in entity_stats.items():
            if s["entity_type"] == "LOC":
                oracle_labels[eid] = False
                continue
            oracle_labels[eid] = bool(
                s["window_agencies"] > s["baseline_agencies"]
                and s["window_daily"] > 1.5 * s["baseline_daily"]
                and s["window_count"] >= min_window_articles
                and s["baseline_agencies"] <= 20
            )

        return {"entity_stats": entity_stats, "oracle_labels": oracle_labels}

    finally:
        conn.close()
