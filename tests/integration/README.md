# Integration Tests

This directory contains integration tests for the data platform.

## Overview

Integration tests validate that components work correctly together with real dependencies (like PostgreSQL) while mocking external services (like Typesense, ML models).

## Test Files

### `test_embedding_workflow.py`

**Complete embedding workflow integration test**

Tests the end-to-end flow:
1. Generate embeddings for 2025 news records
2. Sync embeddings to Typesense
3. Validate data flows correctly through the entire pipeline

**Key Features:**
- Uses real PostgreSQL test database (via pytest-postgresql)
- Mocks external services (Typesense client, SentenceTransformer model)
- Tests both happy path and edge cases
- Validates 2025-only filtering
- Tests batch processing
- Tests incremental sync

**Test Scenarios:**
- Full workflow: generate → sync → validate
- Only 2025 news are processed
- Embeddings stored correctly in PostgreSQL
- Documents sent to Typesense with correct format
- Text preparation strategy (title + summary, fallback to content)
- Incremental sync (only sync updated embeddings)
- Batch processing with different batch sizes
- Edge cases (no records, missing summaries, etc.)

### `test_postgres_integration.py`

**PostgresManager integration tests**

Tests database operations with a real Cloud SQL instance.

## Requirements

### Dependencies

```bash
# Install test dependencies
poetry install --with dev
```

Required packages:
- `pytest` - Test framework
- `pytest-postgresql` - Temporary PostgreSQL instances for testing
- `pytest-cov` - Coverage reporting

### PostgreSQL

The embedding workflow tests use `pytest-postgresql` which:
- Automatically creates a temporary PostgreSQL instance
- Sets up schema and test data
- Cleans up after tests
- No manual setup required!

**Note:** You need PostgreSQL binaries installed on your system:

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt-get install postgresql

# The tests will use these binaries to create temporary test databases
```

## Running Tests

### Run all integration tests

```bash
pytest tests/integration/ -v
```

### Run only embedding workflow tests

```bash
pytest tests/integration/test_embedding_workflow.py -v
```

### Run specific test class

```bash
pytest tests/integration/test_embedding_workflow.py::TestEmbeddingWorkflow -v
```

### Run specific test

```bash
pytest tests/integration/test_embedding_workflow.py::TestEmbeddingWorkflow::test_complete_workflow_generate_and_sync -v
```

### With coverage

```bash
pytest tests/integration/ -v --cov=data_platform --cov-report=html
```

### With detailed output

```bash
pytest tests/integration/ -v -s  # -s shows print statements
```

## Test Database

### Automatic Setup (pytest-postgresql)

The `test_embedding_workflow.py` tests use `pytest-postgresql` which:

1. Creates a temporary PostgreSQL cluster
2. Starts PostgreSQL on a random port
3. Creates test database with schema
4. Runs tests
5. Shuts down and cleans up

**No manual setup required!**

### Schema

The test database includes:
- `agencies` table (3 sample agencies)
- `themes` table (6 sample themes across 3 levels)
- `news` table (13 sample records: 10 from 2025, 3 from 2024)
- `sync_log` table

### Test Data

Sample data inserted automatically:

**Agencies:**
- MEC (Ministério da Educação)
- Saúde (Ministério da Saúde)
- Fazenda (Ministério da Fazenda)

**Themes:**
- Level 1: Educação, Saúde
- Level 2: Ensino Superior, Política de Saúde
- Level 3: Universidades, SUS

**News:**
- 10 records from January 2025 (with summaries)
- 3 records from December 2024 (should NOT be processed)

## Mocking Strategy

### What is Mocked

1. **SentenceTransformer model** - Generates random normalized embeddings (768 dimensions)
2. **Typesense client** - Simulates successful document imports
3. **External HTTP calls** - None needed (all external services are mocked)

### What is Real

1. **PostgreSQL database** - Real database operations (via pytest-postgresql)
2. **Data processing logic** - Real embedding generation and sync code
3. **Database transactions** - Real commit/rollback behavior

## Understanding Test Output

### Successful run

```
tests/integration/test_embedding_workflow.py::TestEmbeddingWorkflow::test_complete_workflow_generate_and_sync PASSED
```

### Failed test

```
tests/integration/test_embedding_workflow.py::TestEmbeddingWorkflow::test_complete_workflow_generate_and_sync FAILED

AssertionError: assert 8 == 10
  Expected 10 embeddings to be generated, but got 8
```

## Troubleshooting

### PostgreSQL binaries not found

**Error:**
```
VersionNotAvailable: Could not find postgresql binary
```

**Solution:**
```bash
# macOS
brew install postgresql

# Linux
sudo apt-get install postgresql
```

### Port already in use

**Error:**
```
OSError: [Errno 48] Address already in use
```

**Solution:**
The tests use random ports. This error usually means PostgreSQL didn't clean up properly. Restart your terminal or run:

```bash
pkill -9 postgres
```

### pgvector extension not available

**Behavior:**
Tests will automatically fall back to using `FLOAT[]` instead of `vector(768)` type.

**To install pgvector (optional):**
```bash
# macOS
brew install pgvector

# From source
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

## CI/CD Integration

These tests are designed to run in CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Install PostgreSQL
  run: |
    sudo apt-get update
    sudo apt-get install -y postgresql

- name: Run integration tests
  run: |
    poetry install --with dev
    poetry run pytest tests/integration/ -v
```

## Performance

Typical test execution times:
- Full test suite: ~30-60 seconds
- Single test: ~5-10 seconds

The temporary PostgreSQL setup adds ~10-15 seconds overhead (one-time per test session).

## Best Practices

1. **Keep tests independent** - Each test should set up and clean up its own data
2. **Use fixtures** - Reuse common setup (database, sample data, mocks)
3. **Test one thing** - Each test should validate a single behavior
4. **Descriptive names** - Test names should describe what they validate
5. **Good docstrings** - Explain what the test validates and why
6. **Mock external services** - Never depend on real Typesense, real ML models, etc.
7. **Use real database** - Test actual SQL queries and transactions

## Writing New Tests

### Template

```python
def test_my_new_feature(
    test_database_url,
    sample_2025_news,
    mock_sentence_transformer,
    postgresql
):
    """
    Test description.

    Validates:
    1. First thing
    2. Second thing
    """
    # Arrange
    with patch('module.Class', return_value=mock_object):
        component = Component(database_url=test_database_url)

    # Act
    result = component.do_something()

    # Assert
    assert result['success'] == True

    # Verify database state
    cur = postgresql.cursor()
    cur.execute("SELECT COUNT(*) FROM table")
    count = cur.fetchone()[0]
    assert count == expected_count
```

### Fixtures to Use

- `test_database_url` - Database connection string
- `postgresql` - PostgreSQL connection (for direct queries)
- `setup_test_schema` - Creates schema (auto-used by sample_2025_news)
- `sample_2025_news` - Inserts 10 news from 2025, 3 from 2024
- `mock_sentence_transformer` - Mocked ML model
- `mock_typesense_client` - Mocked Typesense client

## Related Documentation

- [Main README](../../README.md) - Project overview
- [Schema Documentation](../../_plan/SCHEMA.md) - Database schema
- [Unit Tests](../unit/README.md) - Unit test documentation

---

**Last Updated:** 2024-12-27
