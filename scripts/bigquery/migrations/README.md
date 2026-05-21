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
