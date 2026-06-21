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

## MLflow Tracking

Every `evaluate.py` run automatically logs a run to MLflow under the experiment
`trend-detection-autoresearch`. No extra steps needed — `dgb_mlflow.configure()`
reads `DGB_MLFLOW_TRACKING_URI` from `.env` and handles IAP authentication.

Each run logs:
- **Params:** `k_eval_points`, `step_days`, `window_days`, `baseline_days`
- **Metrics:** `ndcg_at_10`, `eval_points`, `avg_oracle_positives`, `total_seconds`
- **Tags:** `git_commit` (short SHA of current commit)
- **Artifact:** `scorer.py` (snapshot of the scorer that produced these results)

View results at: https://destaquesgovbr-mlflow-klvx64dufq-rj.a.run.app

If MLflow is unavailable or auth fails, `evaluate.py` will still produce the
correct stdout output — the MLflow error is non-fatal (it will traceback but
the print at the end still runs). To skip MLflow entirely, set:
`DGB_MLFLOW_TRACKING_URI=sqlite:///mlflow_local.db` in `.env`.

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
