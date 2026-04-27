# Guia de Testes - Data Platform

Este documento descreve a organização, convenções e uso da suíte de testes do `data-platform`.

## Estrutura

A estrutura de testes espelha a organização do código-fonte em `src/data_platform/`, seguindo o princípio de **navegação por reflexo** - você encontra os testes de qualquer módulo pelo caminho previsível.

```
tests/
├── conftest.py                              # Fixtures globais (set_test_environment)
├── unit/                                    # Testes unitários (mocks, sem I/O real)
│   ├── conftest.py                          # Fixtures compartilhadas (mock_sqlalchemy_engine, mock_psycopg2_conn)
│   ├── managers/                            # Testes de managers
│   │   ├── conftest.py                      # pg, mock_conn, mock_dataset_manager_*
│   │   ├── test_postgres_manager.py
│   │   ├── test_dataset_manager.py
│   │   └── test_storage_adapter.py
│   ├── models/                              # Testes de modelos Pydantic
│   ├── jobs/                                # Testes de jobs de processamento
│   │   ├── bigquery/
│   │   ├── integrity/
│   │   ├── similarity/
│   │   ├── thumbnail/
│   │   └── typesense/
│   ├── workers/                             # Testes de workers (Cloud Run services)
│   │   ├── thumbnail_worker/
│   │   │   ├── conftest.py                  # _mock_pg
│   │   │   ├── test_app.py
│   │   │   ├── test_extractor.py
│   │   │   ├── test_handler.py
│   │   │   └── test_storage.py
│   │   ├── feature_worker/
│   │   ├── bronze_writer/
│   │   └── typesense_sync/
│   ├── typesense/                           # Testes do módulo Typesense
│   ├── dags/                                # Testes de DAGs Airflow
│   ├── utils/                               # Testes de utilitários
│   ├── schema/                              # Testes de schema e validação
│   └── config/                              # Testes de configuração
├── scripts/                                 # Testes de scripts de migração
│   ├── conftest.py                          # Setup de sys.path
│   ├── test_migrate_runner.py
│   ├── test_migrate_unique_ids.py
│   └── test_migration_006.py
└── integration/                             # Testes de integração (PostgreSQL real)
    ├── conftest.py                          # Fixtures com conexão real
    ├── README.md
    └── test_postgres_integration.py
```

### Princípios de Organização

- **Espelhamento**: `src/data_platform/managers/postgres_manager.py` → `tests/unit/managers/test_postgres_manager.py`
- **Fixtures por domínio**: cada subdiretório pode ter seu `conftest.py` com fixtures específicas
- **Isolamento**: testes unitários não fazem I/O real (banco, rede, filesystem); testes de integração requerem PostgreSQL

## Nomenclatura

### Arquivos de teste

Convenção: `test_<module>.py` espelha o nome do módulo testado.

**Exemplos**:

| Módulo fonte | Arquivo de teste |
|--------------|------------------|
| `src/data_platform/managers/postgres_manager.py` | `tests/unit/managers/test_postgres_manager.py` |
| `src/data_platform/workers/feature_worker/features.py` | `tests/unit/workers/feature_worker/test_features.py` |
| `src/data_platform/utils/batch.py` | `tests/unit/utils/test_batch.py` |

### Classes e funções de teste

- Classes: `TestNomeDoModulo`, `TestFuncionalidade` (ex: `TestPostgresManagerCore`, `TestFeatureStoreUpsert`)
- Funções: `test_comportamento_esperado` (ex: `test_get_agency_by_key`, `test_upsert_creates_new_row`)

## Fixtures Compartilhadas

Fixtures reutilizáveis vivem em arquivos `conftest.py` organizados por escopo:

### `tests/conftest.py` (escopo global)

- **`set_test_environment`** (session, autouse): configura variáveis de ambiente (`TESTING=1`, `STORAGE_BACKEND=huggingface`)

### `tests/unit/conftest.py` (unitários)

- **`mock_sqlalchemy_engine`**: mock de SQLAlchemy engine com suporte a `with engine.begin() as conn`
- **`mock_psycopg2_conn`**: mock de conexão psycopg2 com cursor e context manager (stateless)

### `tests/unit/managers/conftest.py` (managers)

- **`pg`**: `PostgresManager` com pool e engine mockados (sem DB real)
- **`mock_conn`**: mock de conexão do pool
- **`mock_dataset_manager_base`**: `DatasetManager` com token mockado
- **`mock_dataset_manager_full`**: `DatasetManager` com todos os métodos mockados

### `tests/unit/workers/thumbnail_worker/conftest.py` (thumbnail_worker)

- **`_mock_pg`**: mock de `PostgresManager` para evitar conexão real no lifespan da app

### `tests/scripts/conftest.py` (scripts)

- Setup automático de `sys.path` apontando para `scripts/` e `scripts/migrations/`

## Padrão AAA (Arrange-Act-Assert)

Estruture testes seguindo o padrão **Arrange-Act-Assert**:

```python
def test_get_agency_by_key(pg):
    # Arrange - preparar dados e estado
    agency = Agency(id=1, key="mec", name="Ministério da Educação")
    pg._agencies_by_key["mec"] = agency
    pg._cache_loaded = True

    # Act - executar a ação testada
    result = pg.get_agency_by_key("mec")

    # Assert - verificar o resultado
    assert result is not None
    assert result.key == "mec"
    assert result.name == "Ministério da Educação"
```

Seções podem ser separadas por linhas em branco para clareza. Comentários AAA são opcionais.

## Custom Markers

Markers permitem categorizar e filtrar testes:

- **`@pytest.mark.integration`**: testes de integração (requerem PostgreSQL real)
- **`@pytest.mark.slow`**: testes lentos (> 1s)
- **`@pytest.mark.requires_db`**: requer conexão com banco de dados
- **`@pytest.mark.requires_network`**: requer acesso à rede (APIs externas)

Markers estão registrados em `pyproject.toml` (seção `[tool.pytest.ini_options]`).

**Exemplo de uso**:

```python
@pytest.mark.integration
@pytest.mark.requires_db
def test_upsert_creates_new_row(pg):
    # Este teste requer PostgreSQL real
    ...
```

## Como Rodar

### Comandos Make

```bash
# Rodar todos os testes (unitários + integração)
make test

# Apenas testes unitários (rápido, sem DB)
make test-unit

# Apenas testes de integração (requer PostgreSQL)
make test-integration
```

### Comandos pytest diretos

```bash
# Rodar testes de um diretório específico
pytest tests/unit/managers/

# Rodar um arquivo específico
pytest tests/unit/managers/test_postgres_manager.py

# Rodar um teste específico
pytest tests/unit/managers/test_postgres_manager.py::TestPostgresManagerCore::test_init

# Excluir testes lentos
pytest -m "not slow"

# Apenas testes de integração
pytest -m integration

# Com cobertura detalhada
pytest --cov=data_platform --cov-report=html
```

### Verificação rápida

```bash
# Rodar apenas testes afetados por mudanças (requires pytest-testmon)
pytest --testmon

# Parar no primeiro erro
pytest -x

# Modo verboso com output completo
pytest -vv -s
```

## Boas Práticas

1. **Use fixtures em vez de setup/teardown**: fixtures são mais composíveis e explícitas
2. **Isole I/O real em testes de integração**: testes unitários devem usar mocks
3. **Nomeie testes descritivamente**: `test_upsert_creates_new_row` é melhor que `test_upsert`
4. **Mantenha testes focados**: um teste deve verificar um comportamento específico
5. **Evite lógica complexa em testes**: testes devem ser fáceis de ler e entender
6. **Use custom markers**: facilita rodar subconjuntos de testes durante desenvolvimento

## Troubleshooting

### Testes falhando com import errors

- Verifique se você está rodando via `make test` (configura `PYTHONPATH=src`)
- Ou rode: `PYTHONPATH=src pytest tests/`

### Testes de integração falhando

- Certifique-se de que PostgreSQL está rodando: `make docker-up`
- Verifique variáveis de ambiente: `DATABASE_URL` deve estar configurada
- Popule dados mestres: `make setup-db`

### Coverage report não gerado

- Rode com flag explícita: `pytest --cov=data_platform --cov-report=html`
- Relatório HTML estará em `htmlcov/index.html`

---

**Última atualização**: 2026-04-24 (Issue #136 - Fase 1)
