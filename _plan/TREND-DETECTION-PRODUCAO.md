# Plano: Trend Detection → Produção

## Contexto

O autoresearch loop (PR data-platform#188, mergeado) produziu `scorer.py` com NDCG@10 = 1.0. Agora precisamos produtizar:

- **data-platform**: DAG que roda `load_snapshot` + `compute_scores` e persiste em nova tabela `entity_trending_scores`
- **graphql-api**: resolver `trendingEntities` que lê essa tabela e expõe via GraphQL

`trendingThemes` atual usa Typesense com volumetria de tema — permanece intocado. O novo endpoint é complementar (entidades NER em vez de temas).

---

## PR 1 — data-platform

### 1. Migration `025_entity_trending_scores.sql`

```sql
CREATE TABLE IF NOT EXISTS entity_trending_scores (
    entity_id          TEXT        NOT NULL,
    canonical_name     TEXT        NOT NULL,
    type               TEXT        NOT NULL,
    trending_score     FLOAT       NOT NULL,
    window_count       INTEGER     NOT NULL,
    window_agencies    INTEGER     NOT NULL,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (entity_id)
);
CREATE INDEX IF NOT EXISTS idx_entity_trending_score
    ON entity_trending_scores (trending_score DESC);
```

Aplicar via `db-migrate.yaml` após merge.

### 2. Job functions `src/data_platform/jobs/trend_detection/`

Copiar e adaptar `research/trend-detection/scorer.py` e `signals.py` para o caminho de produção. Diferenças vs. versão de pesquisa:
- `load_snapshot(db_url: str, date_end: date) -> dict` — aceita `db_url` como parâmetro (padrão do repo), sem ler env direto
- `compute_scores(data: dict) -> list[tuple[str, float]]` — inalterado (função pura)
- `upsert_trending_scores(db_url: str, scores: list[tuple[str, float]], entity_stats: dict) -> int` — novo; usa padrão SQLAlchemy + NullPool do repo

Arquivos:
- `__init__.py` — vazio
- `signals.py` — `load_snapshot()` adaptada
- `scorer.py` — cópia fiel de `research/trend-detection/scorer.py`
- `persist.py` — `upsert_trending_scores()` com UPSERT idempotente

Padrão UPSERT de `persist.py`:
```sql
INSERT INTO entity_trending_scores
    (entity_id, canonical_name, type, trending_score, window_count, window_agencies, computed_at)
VALUES (:entity_id, :canonical_name, :type, :score, :window_count, :window_agencies, NOW())
ON CONFLICT (entity_id) DO UPDATE SET
    trending_score  = EXCLUDED.trending_score,
    window_count    = EXCLUDED.window_count,
    window_agencies = EXCLUDED.window_agencies,
    computed_at     = EXCLUDED.computed_at
```

### 3. DAG `src/data_platform/dags/compute_entity_trending.py`

```python
@dag(schedule="0 */6 * * *", ...)  # 4× por dia, mesmo ritmo do canon backfill
def compute_entity_trending():
    @task()
    def run(**context):
        from data_platform.jobs.trend_detection.signals import load_snapshot
        from data_platform.jobs.trend_detection.scorer import compute_scores
        from data_platform.jobs.trend_detection.persist import upsert_trending_scores
        from datetime import date
        pg_conn = BaseHook.get_connection("postgres_default")
        db_url = pg_conn.get_uri().replace("postgres://", "postgresql://", 1)
        data = load_snapshot(db_url, date_end=date.today())
        scores = compute_scores(data)
        count = upsert_trending_scores(db_url, scores, data["entity_stats"])
        return {"status": "ok", "count": count}
    run()
```

### 4. Testes (TDD)

**`tests/unit/jobs/test_trend_detection_scorer.py`** — testes da função pura `compute_scores`:
- LOC filtrado
- entities com window_count < 3 excluídas
- volume_ratio ≤ 1.5 excluído
- baseline_agencies > 20 excluído
- window_agencies ≤ baseline_agencies excluído
- ordenação por score DESC
- resultado vazio quando nenhuma entity passa nos filtros

**`tests/unit/jobs/test_trend_detection_persist.py`** — testes de `upsert_trending_scores()` com mock de `mock_sqlalchemy_engine` (fixture já existe em `tests/unit/conftest.py`):
- UPSERT executado para cada score
- retorna contagem correta
- ignora entities sem `canonical_name` ou `type` nos stats

**`tests/unit/dags/test_compute_entity_trending.py`** — teste AST:
- airflow importado em `try/except ImportError`
- DAG tem `max_active_runs=1`

Todos os testes escritos **antes** das implementações (TDD).

---

## PR 2 — graphql-api

### 1. Novo tipo `types/entities.py`

```python
@strawberry.type
class TrendingEntityResult:
    entity_id: str
    canonical_name: str
    type: str
    trending_score: float
    window_count: int
    window_agencies: int
    computed_at: Optional[str]
```

### 2. Método `PostgresDatasource.get_trending_entities()` em `datasources/postgres.py`

```python
_TRENDING_ENTITIES_SQL = """
    SELECT entity_id, canonical_name, type,
           trending_score, window_count, window_agencies,
           computed_at::text
    FROM entity_trending_scores
    ORDER BY trending_score DESC
    LIMIT $1
"""

async def get_trending_entities(self, limit: int = 10) -> list[dict]:
    async with self._pool.acquire() as conn:
        rows = await conn.fetch(_TRENDING_ENTITIES_SQL, limit)
    return [dict(r) for r in rows]
```

### 3. Resolver em `resolvers/entities.py`

Adicionar ao `EntityQuery` existente:

```python
@strawberry.field(description="Entidades NER com maior crescimento de cobertura (pré-computado)")
async def trending_entities(
    self,
    info: Info,
    limit: int = 10,
) -> list[TrendingEntityResult]:
    ds = info.context.postgres_ds
    rows = await ds.get_trending_entities(min(limit, 50))
    return [
        TrendingEntityResult(
            entity_id=row["entity_id"],
            canonical_name=row.get("canonical_name") or "",
            type=row.get("type") or "",
            trending_score=float(row.get("trending_score") or 0.0),
            window_count=int(row.get("window_count") or 0),
            window_agencies=int(row.get("window_agencies") or 0),
            computed_at=row.get("computed_at"),
        )
        for row in rows
    ]
```

### 4. Testes (TDD) em `tests/resolvers/test_entities.py`

Escritos antes da implementação:
- `trendingEntities` retorna lista com campos corretos
- `limit` clampado a 50
- datasource chamado com `limit` correto
- lista vazia quando datasource retorna `[]`

### 5. SDL snapshot

Após implementar, regenerar `docs/reference/schema.graphql`:
```bash
cd graphql-api && poetry run python scripts/dump_schema.py
```
Commitar o diff — drift gate do portal valida este arquivo.

---

## Ordem de execução

1. **Escrever testes** (scorer, persist, DAG, resolver) — todos devem falhar inicialmente
2. **Implementar** jobs + DAG até testes passarem
3. **Implementar** resolver + datasource até testes passarem
4. **Criar migration** 025 (não requer código de teste)
5. **Regenerar SDL snapshot** no graphql-api
6. **Abrir PRs** — data-platform primeiro; graphql-api pode ser paralelo mas precisa da tabela para integração

---

## Verificação end-to-end

1. Aplicar migration 025 em staging via `db-migrate.yaml`
2. Fazer merge do PR data-platform → Composer detecta o DAG, primeira run em até 6h
3. Confirmar linhas em `entity_trending_scores`: `SELECT COUNT(*) FROM entity_trending_scores;`
4. Fazer merge do PR graphql-api → deploy automático
5. Testar via curl ou playground:
   ```graphql
   { trendingEntities(limit: 5) { entityId canonicalName type trendingScore } }
   ```

---

## Fora de escopo (follow-ups)

- **Portal**: exibir `trendingEntities` na homepage ou `/entidades` — PR separado após graphql-api deployado
- **`window_daily` / `baseline_daily`** na tabela — pode ser útil para debug; não necessário para v1
- **Reprocessamento histórico** — scorer roda apenas sobre janela atual; comparação histórica via MLflow
