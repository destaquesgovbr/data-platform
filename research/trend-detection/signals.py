"""
signals.py — carregamento de dados e oracle (NÃO MODIFICAR).

Carrega um snapshot temporal de dados de entidades do PostgreSQL e
computa os oracle_labels usados para avaliar o scorer.

Oracle: uma entidade é "trending" se:
  - entity_type != 'LOC'  (LOC excluído — muito ruído geográfico)
  - window_daily > 1.5 * baseline_daily  (crescimento de volume)
  - window_agencies > baseline_agencies  (expansão inter-agência)
  - window_count >= min_window_articles
  - baseline_agencies <= 20  (excluir "permanentes": Brasil, Brasília, Lula, etc.)
"""

import os
from datetime import date, timedelta
from typing import Optional

import numpy as np
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


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
    window_days: int = 7,
    baseline_days: int = 28,
    date_end: Optional[date] = None,
    min_window_articles: int = 3,
) -> dict:
    """
    Retorna dict com entity_stats e oracle_labels para uma janela temporal.

    entity_stats[entity_id] = {
        'canonical_name': str,
        'entity_type': str,          # ORG|PER|EVENT|POLICY|LAW|LOC
        'window_count': int,
        'baseline_count': int,
        'window_daily': float,       # window_count / window_days
        'baseline_daily': float,     # baseline_count / baseline_days (min 0.001)
        'window_agencies': int,
        'baseline_agencies': int,
        'semantic_novelty': float,   # avg(1 - cosine_sim(window_emb, baseline_centroid))
        'new_edge_count': int,       # edges com first_seen na janela
    }
    oracle_labels[entity_id] = True | False
    """
    if date_end is None:
        date_end = date.today()

    window_start = date_end - timedelta(days=window_days)
    # baseline é o período anterior à janela (não-sobreposto)
    baseline_start = date_end - timedelta(days=window_days + baseline_days)

    conn = _get_conn()
    try:
        # ── 1. Volume e agências ────────────────────────────────────────────
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

        # ── 2. Novas arestas de co-menção ───────────────────────────────────
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

        # ── 3. Novidade semântica via pgvector ──────────────────────────────
        # Baseline: embeddings do período anterior à janela
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

        # Centroides por entidade
        centroids: dict[str, np.ndarray] = {}
        for eid, embs in baseline_embs.items():
            arr = np.array(embs, dtype=np.float32)
            centroids[eid] = arr.mean(axis=0)

        # Window: embeddings da janela recente
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

        # ── 4. Oracle labels ────────────────────────────────────────────────
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
