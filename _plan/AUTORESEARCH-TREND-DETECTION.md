# Autoresearch — Detecção de Tendências por Metadados

## Contexto

O `detect_trends` atual (graphql-api `trendingThemes`) conta artigos por tema no Typesense via facets — pura volumetria de tema, sem considerar entidades NER canônicas, embeddings ou topologia do grafo.

O objetivo: evoluir o algoritmo usando os metadados ricos das notícias e aplicar o **padrão autoresearch do Karpathy** ([github.com/karpathy/autoresearch](https://github.com/karpathy/autoresearch)) — um agente AI modifica um único arquivo de scorer (`scorer.py`), mede uma métrica objetiva (`ndcg@10`), mantém se melhorou, e repete indefinidamente overnight. Você acorda com 50–100 experimentos rodados e (esperançosamente) um scorer melhor.

### Analogia autoresearch → trend-detection

| autoresearch | trend-detection |
|---|---|
| `train.py` (arquivo mutável) | `scorer.py` — função de scoring |
| `prepare.py` (harness fixo) | `evaluate.py` — backtesting histórico |
| `val_bpb` (métrica, menor = melhor) | `ndcg@10` (maior = melhor, max 1.0) |
| 5 min de treino por experimento | ~30–60 seg de backtesting por experimento |
| loop keep/discard forever | loop keep/discard forever |

---

## Estado dos Dados (verificado em 2026-06-21)

| Tabela | Linhas | Observação |
|---|---|---|
| `news` | 336,012 | 99.6% com `content_embedding` (vector 768-dim HNSW) |
| `news_features` | 27,671 | NER backfill em progresso — ~8% do total, mas cobre os últimos 60 dias densamente |
| `news_entities` | 75,662 menções | 21,042 artigos × 3,833 entidades distintas; `published_at` denormalizado |
| `entity_registry` | 4,647 | 1,957 ORG, 1,135 LOC, 406 POLICY, 325 EVENT, 250 LAW, 186 PER |
| `entity_edges` | 19,990 | mostly `co_mention` (19,948); `first_seen`/`last_seen` disponíveis |

**Cobertura de entidades por dia (últimas semanas):**
- Dias úteis: ~300–340 artigos com entidades
- Fins de semana: 28–50 artigos (backfill roda 4×/dia mas o scraper publica menos)
- Total dos últimos 30 dias: ~28,600 menções

**Oracle candidate (validado no banco):**
- Entities no window (7 dias): ~975
- Com spread multi-agência (≥2 agências): ~455
- Com crescimento real (volume +50% E agências crescendo): ~163
- "Permanentes" a excluir (>20 agências no baseline): 79

---

## Schema das Tabelas Relevantes

```sql
-- Artigos com embeddings
news (
    unique_id VARCHAR(120) PK,
    agency_key VARCHAR,
    agency_name VARCHAR,
    published_at TIMESTAMPTZ,
    content_embedding vector(768)  -- HNSW cosine index
)

-- Menções normalizadas: 1 row per article × canonical entity
news_entities (
    unique_id VARCHAR(120) FK → news,
    entity_id VARCHAR(64) FK → entity_registry,
    type VARCHAR(16),
    count INTEGER,         -- mention frequency in article
    salience REAL,
    published_at TIMESTAMPTZ,  -- denormalizado de news para queries temporais
    PK (unique_id, entity_id)
)

-- Entidades canônicas
entity_registry (
    entity_id VARCHAR(64) PK,   -- QID ("Q216330") ou "dgb_<ulid>"
    canonical_name TEXT,
    type VARCHAR(16),           -- ORG|PER|LOC|EVENT|POLICY|LAW
    aliases JSONB,
    wikidata_id VARCHAR,
    description TEXT,
    agency_key VARCHAR
)

-- Grafo de co-menção
entity_edges (
    src_id VARCHAR(64) FK → entity_registry,
    dst_id VARCHAR(64) FK → entity_registry,
    kind VARCHAR(20),       -- 'co_mention' (undirected, src < dst), 'subordinate_to', 'is_agency'
    weight INTEGER,         -- número de artigos com ambas entidades
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    PK (src_id, dst_id, kind)
)
```

---

## Fase A — Setup e Loop de Pesquisa

### Estrutura de arquivos a criar

```
data-platform/
└── research/
    └── trend-detection/
        ├── program.md          ← instruções para o agente AI
        ├── evaluate.py         ← harness fixo (NÃO modificar)
        ├── signals.py          ← carregamento de dados (NÃO modificar)
        ├── scorer.py           ← scorer mutável (o agente modifica este)
        ├── requirements.txt
        ├── .env.example
        └── .gitignore
```

### Setup do ambiente

```bash
# 1. Obter connection strings do Secret Manager
export DATABASE_URL=$(gcloud secrets versions access latest \
    --secret=govbrnews-postgres-connection-string \
    --project=inspire-7-finep)

# 2. Criar diretório e venv (Python 3.12+ obrigatório — dgb-mlflow requer >=3.11)
cd /Users/nitai/dev/destaquesgovbr/data-platform
mkdir -p research/trend-detection
cd research/trend-detection

python3.12 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependências (PIP_CONFIG_FILE=/dev/null evita auth prompt do Artifact Registry)
PIP_CONFIG_FILE=/dev/null pip install -r requirements.txt
PIP_CONFIG_FILE=/dev/null pip install /path/to/destaquesgovbr/ml-platform/client

# 4. Criar .env
cat > .env <<EOF
DATABASE_URL=$DATABASE_URL
DGB_MLFLOW_TRACKING_URI=https://destaquesgovbr-mlflow-klvx64dufq-rj.a.run.app
EOF

# 5. Testar conexão DB
python -c "from signals import load_snapshot; d = load_snapshot(); print(len(d['entity_stats']), 'entities,', sum(d['oracle_labels'].values()), 'oracle positives')"
# Esperado: ~400-1000 entities, ~30-150 oracle positives

# 6. Estabelecer baseline
python evaluate.py
# Baseline medido em 2026-06-21: ndcg@10 = 0.727613, total_seconds = 484.6
# Nota: total_seconds é alto (~8 min) por causa de queries de embedding ao DB remoto
```

**Nota sobre total_seconds:** O evaluate.py leva ~484s (20 pontos × queries de embedding pgvector ao DB remoto em 34.39.145.55). Cada iteração do loop autoresearch leva ~8-9 minutos. 50 experimentos overnight = ~7h — viável mas lento.

---

## MLflow Tracking

O evaluate.py loga automaticamente cada run no experimento **`trend-detection-autoresearch`** no MLflow.

| Item | Valor |
|------|-------|
| Server | https://destaquesgovbr-mlflow-klvx64dufq-rj.a.run.app |
| Experiment ID | 4 |
| Auth | IAP + JWT via `dgb-mlflow` (transparente) |
| Artifact store | `gs://inspire-7-finep-mlflow-artifacts` |

**Campos logados por run:**

| Tipo | Campo |
|------|-------|
| Param | `k_eval_points`, `step_days`, `window_days`, `baseline_days` |
| Metric | `ndcg_at_10`, `eval_points`, `avg_oracle_positives`, `total_seconds` |
| Tag | `git_commit` (SHA do commit em avaliação) |
| Artifact | `scorer.py` (snapshot do scorer que produziu o resultado) |

Se o servidor MLflow estiver indisponível, o evaluate.py degrada graciosamente: loga aviso e continua sem MLflow (as métricas stdout e results.tsv continuam funcionando).

---

### `requirements.txt`

```
psycopg2-binary>=2.9
numpy>=1.26
scikit-learn>=1.4
python-dotenv>=1.0
# dgb-mlflow instalado separadamente do repo ml-platform/client
# (puxa mlflow==3.13.0, google-auth, google-cloud-storage)
```

### `.env.example`

```
DATABASE_URL=postgresql://user:password@34.39.145.55:5432/govbrnews
DGB_MLFLOW_TRACKING_URI=https://destaquesgovbr-mlflow-klvx64dufq-rj.a.run.app
```

### `.gitignore`

```
.env
results.tsv
run.log
.venv/
__pycache__/
*.pyc
```

---

### `signals.py` — código completo

```python
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
```

---

### `evaluate.py` — código completo

```python
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
```

---

### `scorer.py` — baseline inicial (arquivo mutável)

```python
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

        volume_ratio = s["window_daily"] / s["baseline_daily"]
        agency_growth = s["window_agencies"] / max(s["baseline_agencies"], 1)

        score = 0.6 * volume_ratio + 0.4 * agency_growth
        results.append((eid, score))

    return sorted(results, key=lambda x: x[1], reverse=True)
```

---

### `program.md` — conteúdo completo (instruções para o agente)

```markdown
# autoresearch — trend detection DGB

This is an experiment to have an LLM autonomously evolve a trend-detection
scorer over the DGB (Destaques Gov.BR) news corpus.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `jun21`).
   The branch `autoresearch/<tag>` must not already exist — fresh run only.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current main.
3. **Read the in-scope files** (all 4 are small — read them all):
   - `program.md` — this file.
   - `evaluate.py` — fixed harness. **Do not modify.**
   - `signals.py` — fixed data loading. **Do not modify.**
   - `scorer.py` — **the only file you edit.**
4. **Verify DB connection**:
   ```bash
   python -c "from signals import load_snapshot; d = load_snapshot(); print(len(d['entity_stats']), 'entities,', sum(d['oracle_labels'].values()), 'oracle positives')"
   ```
   Should print ~500–1000 entities and ~50–150 oracle positives.
   If `.env` is missing: `echo "DATABASE_URL=<conn_string>" > .env`
   Get conn_string with:
   `gcloud secrets versions access latest --secret=govbrnews-postgres-connection-string --project=inspire-7-finep`
5. **Initialize results.tsv** with just the header:
   ```
   commit	ndcg@10	total_seconds	status	description
   ```
6. **Confirm and go.**

## Experimentation

Each experiment:
1. Modify `scorer.py`
2. `git commit`
3. `python evaluate.py > run.log 2>&1`
4. `grep "^ndcg@10:\|^total_seconds:" run.log`
5. Log to `results.tsv`
6. Keep if ndcg@10 improved; `git reset --hard HEAD~1` if not

**What you CAN do:**
- Modify `scorer.py` only. Everything is fair game: weights, normalization,
  combination functions, thresholds, new derived signals from the data dict.

**What you CANNOT do:**
- Modify `evaluate.py` or `signals.py`.
- Install new packages.
- Access the database in `scorer.py` (all data comes via the `data` dict).
- Modify the oracle definition.

**Goal: maximize ndcg@10.** Current baseline with 2 signals: ~0.2–0.4.

**Simplicity criterion**: a tiny improvement that adds 30 lines of code is
probably not worth it. A simplification that maintains NDCG is always worth it.

**First run**: always run evaluate.py as-is to establish the baseline.

## Available signals in `data['entity_stats'][entity_id]`

| Field              | Type  | Description                                                   |
|--------------------|-------|---------------------------------------------------------------|
| `canonical_name`   | str   | e.g. "Ministério da Educação"                                 |
| `entity_type`      | str   | ORG \| PER \| EVENT \| POLICY \| LAW \| LOC                   |
| `window_count`     | int   | Articles mentioning this entity in the window (last 7 days)   |
| `baseline_count`   | int   | Articles in the baseline (days −35 to −7)                     |
| `window_daily`     | float | window_count / 7                                              |
| `baseline_daily`   | float | baseline_count / 28 (min 0.001 to avoid div/0)                |
| `window_agencies`  | int   | Distinct government agencies covering this entity in window   |
| `baseline_agencies`| int   | Distinct agencies in baseline                                 |
| `semantic_novelty` | float | avg cosine distance of window articles from baseline centroid |
|                    |       | (0 = same context, 1 = entirely new semantic context)         |
| `new_edge_count`   | int   | Co-mention edges with first_seen in the window                |

Note: LOC entities (states, regions) are in entity_stats but excluded from
oracle_labels (they're too generic). The scorer may still use them as features.

## Oracle (for reference — do not modify)

An entity is marked as oracle-positive if ALL of:
- entity_type != 'LOC'
- window_daily > 1.5 × baseline_daily
- window_agencies > baseline_agencies
- window_count >= 3
- baseline_agencies <= 20 (not a "permanent" entity like "Brasil" or "Lula")

## Output format

```
---
ndcg@10:          0.412345
eval_points:      20
avg_oracle_pos:   87.3
total_seconds:    52.1
```

Extract with: `grep "^ndcg@10:\|^total_seconds:" run.log`

## Logging results

`results.tsv` (tab-separated, NOT comma — commas break in descriptions):

```
commit	ndcg@10	total_seconds	status	description
a1b2c3d	0.000000	52.1	keep	baseline (2 signals, equal weights)
```

Columns:
1. git commit hash (short, 7 chars)
2. ndcg@10 (use 0.000000 for crashes)
3. total_seconds from run.log (use 0.0 for crashes)
4. status: `keep`, `discard`, or `crash`
5. Short description of what was tried

## The experiment loop

LOOP FOREVER:

1. Look at git state: current branch + last commit
2. Modify `scorer.py` with an experimental idea
3. `git commit -m "experimento: <short description>"`
4. `python evaluate.py > run.log 2>&1`
5. `grep "^ndcg@10:\|^total_seconds:" run.log`
6. If output is empty → crashed. `tail -50 run.log` for traceback. Fix if trivial; log `crash` and skip if not.
7. Log to results.tsv
8. If ndcg@10 improved → advance (keep commit)
9. If equal or worse → `git reset --hard HEAD~1` (revert scorer.py to last keep)

**NEVER STOP**: Once the loop begins, do NOT pause to ask if you should
continue. The user may be asleep. Run until manually interrupted.

If you run out of ideas:
- Try log-transform on volume_ratio: `math.log1p(volume_ratio)`
- Try multiplicative combination: `volume_ratio * agency_growth`
- Try entity-type weights: boost EVENT/POLICY, reduce PER
- Try rank fusion: convert each signal to a rank, sum ranks
- Try min_window_articles threshold (currently 3) → tune to 2 or 5
- Try geometric mean instead of arithmetic
- Try adding semantic_novelty as third signal
- Try adding new_edge_count as fourth signal
- Try normalizing each signal against its distribution across all entities
- Try harmonic mean of signals
```

---

## Fase B — Deployment (após scorer vencedor)

Após o loop autoresearch produzir um scorer com NDCG@10 significativamente melhor que o baseline, extrair para o pipeline produtivo:

### 1. Migration nova tabela `entity_trends`

Criar `data-platform/scripts/migrations/024_create_entity_trends.sql`:

```sql
CREATE TABLE entity_trends (
    entity_id        VARCHAR(64) NOT NULL REFERENCES entity_registry(entity_id),
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score            REAL NOT NULL,
    rank             INTEGER NOT NULL,
    signal_breakdown JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (entity_id, computed_at)
);
CREATE INDEX idx_entity_trends_rank ON entity_trends (computed_at DESC, rank ASC);
```

### 2. Novo DAG `compute_entity_trends`

Arquivo: `data-platform/src/data_platform/dags/compute_entity_trends.py`

- Extrair scorer vencedor para `jobs/trends/scorer.py`
- Roda diariamente às **08:00 UTC** (após `project_entity_graph` das 06:30)
- Writes: INSERT INTO entity_trends + DELETE rows older than 7 days

### 3. graphql-api: novo resolver `trendingEntities`

Arquivos a modificar:
- `graphql-api/src/graphql_api/schema/types/analytics.py` — novo tipo `TrendingEntityResult`
- `graphql-api/src/graphql_api/schema/resolvers/analytics.py` — novo field `trending_entities`
- `graphql-api/src/graphql_api/datasources/postgres.py` — novo método `trending_entities()`

Seguindo o padrão de `trendingThemes` já existente.

### 4. gobus-mcp: atualizar `detect_trends`

Arquivo: `gobus-mcp/src/gobus_mcp/tools/detect_trends.py`

- Adicionar query GraphQL `trendingEntities` em paralelo com `trendingThemes` existente
- Output: seção "Temas em Alta" (atual) + nova seção "Entidades em Alta"

---

## Verificação

### Fase A — harness pronto

```bash
cd data-platform/research/trend-detection
source .venv/bin/activate
python evaluate.py
# Esperado: ndcg@10 ~0.2-0.5, total_seconds < 90

# Smoke test de sinais
python -c "
from signals import load_snapshot
d = load_snapshot()
stats = d['entity_stats']
print(f'{len(stats)} entities')
print(f'{sum(d[\"oracle_labels\"].values())} oracle positives')
sample = list(stats.items())[:3]
for eid, s in sample:
    print(s['canonical_name'], s['entity_type'], 'vol=', round(s['window_daily'],2), 'nov=', round(s['semantic_novelty'],3))
"
```

### Após loop overnight

```bash
wc -l results.tsv       # esperado: 50-100+ linhas
sort -t$'\t' -k2 -rn results.tsv | head -5  # top experiments por ndcg@10
```

### Fase B — deployment

```bash
# Verificar tabela entity_trends após primeiro DAG run
psql $DATABASE_URL -c "
SELECT rank, er.canonical_name, er.type, et.score
FROM entity_trends et
JOIN entity_registry er USING (entity_id)
WHERE computed_at = (SELECT MAX(computed_at) FROM entity_trends)
ORDER BY rank LIMIT 10;
"

# Verificar graphql-api
curl -sf -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ trendingEntities(limit: 10) { canonicalName type score rank } }"}'
```

---

## Ficheiros críticos existentes (consulta rápida)

| Arquivo | Conteúdo relevante |
|---|---|
| `graphql-api/src/graphql_api/schema/resolvers/analytics.py:176` | `trendingThemes` resolver — padrão para `trendingEntities` |
| `graphql-api/src/graphql_api/schema/types/analytics.py` | `TrendingThemeResult` — padrão para `TrendingEntityResult` |
| `graphql-api/src/graphql_api/datasources/postgres.py` | `agency_analytics()` — padrão para `trending_entities()` |
| `gobus-mcp/src/gobus_mcp/tools/detect_trends.py` | Tool atual a ser atualizada na Fase B |
| `data-platform/src/data_platform/dags/project_entity_graph.py` | DAG predecessor do compute_entity_trends |
