# BigQuery Migrations

Forward-only SQL migrations for the `dgb_gold` dataset.

## Convenção

- Arquivo: `NNN_description.sql` (ex: `001_add_content_hash_to_fato_noticias.sql`)
- Forward-only (sem rollback automático)
- Usar `IF NOT EXISTS` / `IF EXISTS` para idempotência
- Referenciar PR/issue no comentário SQL

## Executar

```bash
# Ver status
python scripts/bq_migrate.py status

# Aplicar pendentes (dry-run)
python scripts/bq_migrate.py migrate --dry-run

# Aplicar de verdade
python scripts/bq_migrate.py migrate

# Histórico
python scripts/bq_migrate.py history

# Validar arquivos (offline, sem BigQuery)
python scripts/bq_migrate.py validate
```

## CI/CD

Workflow manual: `.github/workflows/bq-migrate.yaml`

## Importante

Ao modificar o schema em `sync_to_bigquery.py`, sempre:
1. Criar migration aqui
2. Atualizar `create_tables.sql`
3. Rodar `pytest tests/unit/jobs/bigquery/test_sync_to_bigquery.py::TestSchemaConsistency`

## Tema 26 (002 + MERGE a partir da auditoria)

- `002_tema26_remap_fato_noticias.sql`: remap determinístico de `fato_noticias` (códigos e
  rótulos de l1, l2 e most_specific), com a mesma regra da migração Postgres 034. Aplicar
  depois da 034, na D0.
- A reclassificação por LLM (D1) não é migração: `data-platform bq-merge-theme-changes`
  [--dry-run] [--campaign <campanha ou padrão LIKE> ...] lê do Postgres o estado atual dos
  artigos que aparecem em `news_theme_changes`, carrega em `dgb_gold._stg_news_theme_changes`
  e faz MERGE no fato onde diverge. O padrão default, `tema26-%`, pega todas as campanhas do
  tema 26: `tema26-034` (migração 034), `tema26-llm-d1` (LLM da D1) e `tema26-rollback`. As
  stats trazem `by_campaign` (artigos por campanha): no dry-run da D1, conferir que
  `tema26-llm-d1` aparece. É reexecutável (D0, D1, depois de um rollback), por isso fica fora
  do runner forward-only.
