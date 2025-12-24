# Checklist de Verificação por Fase

> **Instruções**: Marque cada item conforme for completado. Não prossiga para a próxima fase sem completar todos os itens críticos (marcados com *).

---

## Fase 0: Setup Inicial

### Estrutura do Repositório

- [ ] * Diretório `src/data_platform/` criado
- [ ] * Diretório `src/data_platform/managers/` criado
- [ ] * Diretório `src/data_platform/jobs/` criado
- [ ] * Diretório `tests/` criado
- [ ] * Diretório `scripts/` criado
- [ ] `__init__.py` em todos os pacotes

### Configuração

- [ ] * `pyproject.toml` criado com dependências
- [ ] * `.gitignore` configurado
- [ ] `README.md` do repositório
- [ ] `CLAUDE.md` com contexto do projeto
- [ ] `.github/workflows/` (básico para CI)

### Validação

```bash
# Comando de verificação
cd /Users/nitai/Dropbox/dev-mgi/destaquesgovbr/data-platform
poetry install  # ou pip install -e .
pytest tests/   # deve rodar sem erros (mesmo sem testes)
```

- [ ] Poetry/pip install funciona sem erros
- [ ] Pytest roda sem erros

---

## Fase 1: Infraestrutura

### Terraform (no repo infra)

- [ ] * `cloud_sql.tf` criado
- [ ] * `google_sql_database_instance` configurado
- [ ] * `google_sql_database` configurado
- [ ] * `google_sql_user` configurado
- [ ] Networking configurado (se necessário)
- [ ] * Secrets no Secret Manager

### Validação de Conexão

```bash
# Teste de conexão via Cloud SQL Proxy
cloud_sql_proxy -instances=PROJECT:REGION:INSTANCE=tcp:5432 &
psql "postgresql://user:pass@localhost:5432/govbrnews" -c "SELECT 1"
```

- [ ] * Cloud SQL Proxy funciona
- [ ] * Conexão via psql funciona
- [ ] * Pode criar tabelas de teste

### Secrets

| Secret | Criado | Testado |
|--------|--------|---------|
| `GOVBRNEWS_DB_HOST` | [ ] | [ ] |
| `GOVBRNEWS_DB_PORT` | [ ] | [ ] |
| `GOVBRNEWS_DB_NAME` | [ ] | [ ] |
| `GOVBRNEWS_DB_USER` | [ ] | [ ] |
| `GOVBRNEWS_DB_PASSWORD` | [ ] | [ ] |
| `DATABASE_URL` | [ ] | [ ] |

### GitHub Actions

- [ ] * Workflow consegue acessar secrets
- [ ] * Workflow consegue conectar ao banco

---

## Fase 2: PostgresManager

### Implementação

- [ ] * `postgres_manager.py` criado
- [ ] * Método `__init__` com connection string
- [ ] * Método `get_connection` (context manager)
- [ ] * Método `insert`
- [ ] * Método `update`
- [ ] * Método `get` (por data range)
- [ ] Método `get_by_unique_id`
- [ ] Método `get_all_records`
- [ ] Método `get_count`
- [ ] * Cache de agencies (agency_key → agency_id)
- [ ] * Cache de themes (theme_code → theme_id)
- [ ] Método `get_records_for_hf_sync`
- [ ] Método `mark_as_synced_to_hf`

### StorageAdapter

- [ ] * `storage_adapter.py` criado
- [ ] * Enum `StorageBackend`
- [ ] * Método `insert` com switch de backend
- [ ] * Método `update` com switch de backend
- [ ] * Método `get` com switch de backend
- [ ] Suporte a `STORAGE_BACKEND` env var
- [ ] Suporte a `STORAGE_READ_FROM` env var

### Testes Unitários

```bash
pytest tests/test_postgres_manager.py -v
pytest tests/test_storage_adapter.py -v
```

- [ ] * `test_postgres_manager.py` criado
- [ ] * Teste de insert
- [ ] * Teste de update
- [ ] * Teste de get por data
- [ ] Teste de deduplicação
- [ ] * `test_storage_adapter.py` criado
- [ ] * Teste de cada backend
- [ ] Teste de dual-write

### Cobertura

```bash
pytest --cov=data_platform tests/
```

- [ ] Cobertura > 80%

---

## Fase 3: Migração de Dados

### Schema

```bash
python scripts/create_schema.py
```

- [ ] * Tabela `agencies` criada
- [ ] * Tabela `themes` criada
- [ ] * Tabela `news` criada
- [ ] Tabela `sync_log` criada
- [ ] * Índices criados
- [ ] Triggers criados

### Dados Mestres

```bash
python scripts/populate_agencies.py
python scripts/populate_themes.py
```

- [ ] * Agencies populadas (158 registros)
- [ ] * Themes populadas (todas L1, L2, L3)
- [ ] Validação: `SELECT COUNT(*) FROM agencies` = 158
- [ ] Validação: `SELECT COUNT(*) FROM themes WHERE level=1` = ~25

### Migração de News

```bash
python scripts/migrate_hf_to_postgres.py --batch-size 1000
```

- [ ] * Script de migração criado
- [ ] * Migração executada sem erros
- [ ] * Contagem PG == contagem HF

### Validação de Integridade

```bash
python scripts/validate_migration.py
```

| Verificação | Resultado |
|-------------|-----------|
| Contagem total | [ ] OK |
| unique_ids únicos | [ ] OK |
| Todos com agency válida | [ ] OK |
| % com theme preenchido | [ ] > 95% |
| Amostragem de 100 registros | [ ] 100% match |

---

## Fase 4: Dual-Write

### Configuração

- [ ] * `STORAGE_BACKEND=dual_write` configurado
- [ ] * `STORAGE_READ_FROM=huggingface` configurado
- [ ] * Workflow atualizado para usar StorageAdapter

### Execução do Pipeline

| Dia | Data | Scraper OK | Enrichment OK | PG OK | HF OK |
|-----|------|------------|---------------|-------|-------|
| 1 | ____-__-__ | [ ] | [ ] | [ ] | [ ] |
| 2 | ____-__-__ | [ ] | [ ] | [ ] | [ ] |
| 3 | ____-__-__ | [ ] | [ ] | [ ] | [ ] |
| 4 | ____-__-__ | [ ] | [ ] | [ ] | [ ] |
| 5 | ____-__-__ | [ ] | [ ] | [ ] | [ ] |

### Validação Diária

```bash
python scripts/validate_consistency.py
```

- [ ] Contagens coincidem todos os dias
- [ ] Nenhum erro de escrita
- [ ] Logs sem warnings críticos

---

## Fase 5: PostgreSQL como Primary

### Sync Job

- [ ] * `hf_sync_job.py` implementado
- [ ] * Método `run_full_sync`
- [ ] * Método `run_incremental_sync`
- [ ] * Workflow de sync criado

### Switch de Backend

- [ ] * `STORAGE_BACKEND=postgres` configurado
- [ ] * `STORAGE_READ_FROM=postgres` configurado

### Validação

| Dia | Data | Pipeline OK | Sync HF OK | HF Atualizado |
|-----|------|-------------|------------|---------------|
| 1 | ____-__-__ | [ ] | [ ] | [ ] |
| 2 | ____-__-__ | [ ] | [ ] | [ ] |
| 3 | ____-__-__ | [ ] | [ ] | [ ] |
| 4 | ____-__-__ | [ ] | [ ] | [ ] |
| 5 | ____-__-__ | [ ] | [ ] | [ ] |
| 6 | ____-__-__ | [ ] | [ ] | [ ] |
| 7 | ____-__-__ | [ ] | [ ] | [ ] |

- [ ] * 7 dias sem erros
- [ ] * HF atualizado diariamente
- [ ] Lag máximo 24h

---

## Fase 6: Migração de Consumidores

### Typesense

- [ ] * `dataset.py` atualizado para suportar PG
- [ ] * Teste de indexação a partir do PG
- [ ] * Deploy em produção
- [ ] Performance igual ou melhor

### Qdrant

- [ ] `generate-embeddings.py` atualizado
- [ ] Teste de geração de embeddings
- [ ] Deploy em produção

### Outros

- [ ] Streamlit apps atualizados (se aplicável)
- [ ] MCP Server verificado

### Cleanup

- [ ] Documentação atualizada
- [ ] Código legado removido ou deprecado
- [ ] README do scraper atualizado

---

## Verificação Final

### Funcionalidade

- [ ] Pipeline diário funciona 100%
- [ ] Portal exibe notícias corretamente
- [ ] Busca no Typesense funciona
- [ ] HuggingFace é atualizado diariamente

### Performance

- [ ] Tempo de pipeline similar ou melhor
- [ ] Tempo de indexação similar ou melhor
- [ ] Queries no portal < 500ms

### Documentação

- [ ] CLAUDE.md atualizado
- [ ] README.md atualizado
- [ ] Diagramas de arquitetura atualizados

---

*Última atualização: 2024-12-24*
