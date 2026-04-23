# Integration Tests

This directory contains integration tests for the data platform.

## Overview

Integration tests validate that components work correctly together with **real dependencies**:
- Real PostgreSQL database (via Docker)
- Real Typesense server (via Docker)
- Real JSONB operations
- Real SQL queries and JOINs
- Real pagination and date arithmetic

Unlike unit tests (which use mocks), integration tests verify actual database behavior that mocks cannot simulate.

---

## Test Files

### `test_postgres_integration.py`

**Basic PostgresManager integration tests** (7 tests)

Tests core database operations:
- Database connectivity and connection pooling
- Agency/theme cache loading
- Insert, update, get operations
- Duplicate handling (ON CONFLICT DO NOTHING/UPDATE)
- Count with filters

### `test_features_integration.py`

**Feature Store integration tests** (18 tests)

Tests JSONB operations with real PostgreSQL:
- JSONB `||` merge operator (preserve existing keys + overwrite duplicates)
- Nested JSONB structures (3 levels deep)
- Foreign key constraints with CASCADE delete
- Batch queries with missing IDs
- Trigger execution (auto-update `updated_at`)
- Edge cases (NULL values, special characters, numeric precision)

**Why these tests matter:**
- Unit tests only verify SQL syntax
- Integration tests verify actual PostgreSQL JSONB behavior
- Merge semantics with `||` operator can only be validated with real DB

### `test_typesense_query_integration.py`

**Typesense query integration tests** (25 tests)

Tests complex 7-table JOIN queries:
- Query structure (55+ columns, 6 LEFT JOINs)
- JSONB path extraction (`features->'sentiment'->>'label'`)
- Type casting chains (`(features->>'score')::float`)
- Date arithmetic (`published_at < %s::date + INTERVAL '1 day'`)
- NULL propagation in LEFT JOINs
- Pagination consistency (LIMIT/OFFSET without duplicates)
- Count accuracy

**Why these tests matter:**
- Validates the most complex query in the system
- Used for daily PostgreSQL → Typesense sync
- Mocks can't validate JOIN cardinality, NULL handling, or date boundaries

### `test_typesense_e2e_integration.py`

**Typesense E2E sync tests** (10 tests)

Tests complete roundtrip PostgreSQL → Typesense:
- Document preparation (`prepare_document`)
- Schema compatibility
- Batch indexing
- Search and filter operations
- Field preservation (core, theme, feature fields)
- Document updates (upsert)

**Why these tests matter:**
- Validates end-to-end sync pipeline
- Ensures schema changes don't break Typesense integration
- Tests actual search functionality

---

## Requirements

### Dependencies

```bash
# Install with dev dependencies
poetry install --with dev
```

### Docker Infrastructure

Integration tests require Docker services:

```bash
# Start PostgreSQL (port 5433) and Typesense (port 8108)
make docker-up

# Verify containers are running
docker ps | grep destaquesgovbr
```

### Master Data

Tests require agencies and themes to be populated:

```bash
make populate-master
```

This populates:
- **158 agencies** from `test-data/agencies.yaml`
- **588 themes** from `test-data/themes_tree_enriched_full.yaml`

---

## Running Tests

### Run all integration tests

```bash
make test-integration
```

This runs with:
- `--no-cov` flag (coverage disabled for integration tests)
- Proper `DATABASE_URL` environment variable
- Verbose output

### Run specific test file

```bash
PYTHONPATH=src poetry run pytest tests/integration/test_features_integration.py -v --no-cov
```

### Run specific test class

```bash
PYTHONPATH=src poetry run pytest tests/integration/test_typesense_query_integration.py::TestTypesenseQueryExecution -v --no-cov
```

### Run specific test

```bash
PYTHONPATH=src poetry run pytest tests/integration/test_postgres_integration.py::TestPostgresIntegration::test_connection -v --no-cov
```

### Run with marker

```bash
# Only integration tests
pytest -m integration -v

# Skip integration tests (run unit tests only)
pytest -m "not integration" -v
```

### Run E2E tests (requires Typesense)

```bash
# Set Typesense environment variables
export TYPESENSE_HOST=localhost
export TYPESENSE_PORT=8108
export TYPESENSE_API_KEY=local_dev_key_12345

# Run E2E tests
pytest tests/integration/test_typesense_e2e_integration.py -v --no-cov
```

---

## Test Database

### Docker PostgreSQL

Integration tests use the Docker PostgreSQL container on port 5433.

**Setup:**

```bash
make docker-up         # Start container
make populate-master   # Load agencies + themes
make test-integration  # Run tests
```

### Schema

Tests use the **full production schema**:
- `agencies` (158 records populated from YAML)
- `themes` (588 records populated from YAML)
- `news` (test data created per-test, cleaned up after)
- `news_features` (test data created per-test, cleaned up after)

### Test Data Lifecycle

Tests use the **factory pattern** with automatic cleanup:

1. **Setup**: `news_factory()` creates NewsInsert with unique timestamp-based IDs
2. **Test**: Test runs with test data
3. **Cleanup**: `cleanup_news` fixture deletes test records via `DELETE FROM news`

**Result**: Zero data pollution - all test records are cleaned up automatically.

### Reset Database

To completely reset the database:

```bash
make docker-reset  # Destroys and recreates container
make populate-master  # Re-populate master data
```

---

## Fixtures

### Session-Scoped (Shared across all tests)

- `env_vars`: Configures `DATABASE_URL` environment variable
- `postgres_manager_session`: PostgresManager for read-only operations
- `test_agency`: MEC agency (read-only)
- `test_theme`: Educação theme (read-only)
- `typesense_client`: Typesense client (E2E tests only)

### Function-Scoped (Fresh per test)

- `postgres_manager`: PostgresManager for write operations
- `news_factory`: Factory function to create NewsInsert with unique IDs
- `cleanup_news`: List to track unique_ids for automatic cleanup
- `date_ranges`: Common date ranges (today, yesterday, last_week)
- `typesense_test_data`: 3 news articles with themes + features (Typesense query tests)
- `typesense_test_collection`: Temporary Typesense collection (E2E tests)

### Example Usage

```python
def test_my_feature(
    postgres_manager: PostgresManager,
    news_factory: callable,
    cleanup_news: list[str],
) -> None:
    """Test my feature."""
    # Create test data
    news = news_factory(title="Test News")
    cleanup_news.append(news.unique_id)  # Mark for cleanup
    
    # Insert
    postgres_manager.insert([news])
    
    # Test
    result = postgres_manager.get_by_unique_id(news.unique_id)
    assert result is not None
    
    # Cleanup happens automatically via fixture
```

---

## Understanding Test Output

### Successful run

```
tests/integration/test_features_integration.py::TestFeatureStoreUpsert::test_upsert_merges_features_preserves_existing PASSED [11%]
```

### Failed test

```
tests/integration/test_features_integration.py::TestFeatureStoreUpsert::test_upsert_merges_features_preserves_existing FAILED [11%]

AssertionError: Existing key should be preserved
assert 150 == None
```

### Test cleanup

```
Cleaned up 3 test records
```

This message confirms that the `cleanup_news` fixture successfully deleted test data.

---

## Test Statistics

| Metric | Value |
|--------|-------|
| **Total tests** | 60 |
| **Passing** | 59 (98.3%) |
| **Skipped** | 1 (embeddings test) |
| **Execution time** | ~5.6s |
| **Data pollution** | 0 records |
| **Files** | 4 |
| **Classes** | 12 |

---

## What Integration Tests Validate

Integration tests verify behaviors that **mocks cannot simulate**:

### JSONB Operations
- ✅ `||` merge operator (preserve existing, overwrite duplicates)
- ✅ Nested structures (3+ levels deep)
- ✅ Type casting (Python dict → JSONB → Python dict)
- ✅ Path extraction (`->`→`->>`→`::type`)

### SQL Queries
- ✅ 7-table JOIN cardinality
- ✅ NULL propagation in LEFT JOINs
- ✅ Date arithmetic with INTERVAL
- ✅ EXTRACT(EPOCH/YEAR/MONTH) from timestamps

### Database Constraints
- ✅ Foreign key enforcement
- ✅ CASCADE delete behavior
- ✅ Trigger execution
- ✅ ON CONFLICT DO NOTHING/UPDATE

### Pagination
- ✅ LIMIT/OFFSET consistency
- ✅ No duplicates across batches
- ✅ Consistent ordering (DESC published_at)

### Typesense Integration
- ✅ PostgreSQL → Typesense roundtrip
- ✅ Schema compatibility
- ✅ Search & filter operations
- ✅ Batch indexing

---

## Troubleshooting

### Docker containers not running

**Error:**
```
Database not available: could not connect to server
```

**Solution:**
```bash
make docker-up
docker ps  # Verify containers are running
```

### Master data missing

**Error:**
```
SKIPPED: MEC agency not found - run 'make populate-master'
```

**Solution:**
```bash
make populate-master
```

### Port conflicts

**Error:**
```
port 5433 is already in use
```

**Solution:**
```bash
# Stop conflicting container
docker ps | grep 5433
docker stop <container_id>

# Or use docker-reset
make docker-reset
```

### Typesense tests skipped

**Behavior:**
E2E tests are skipped if Typesense is not available.

**Solution:**
```bash
# Verify Typesense is running
curl http://localhost:8108/health

# Restart if needed
make docker-up
```

---

## Performance

Typical execution times:

| Scope | Time |
|-------|------|
| All integration tests | ~5.6s |
| PostgresManager tests | ~0.5s |
| Feature Store tests | ~1.1s |
| Typesense query tests | ~2.5s |
| E2E tests | ~1.5s |

Performance tips:
- Tests run **without coverage** (54% faster)
- Connection pooling reduces overhead
- Automatic cleanup is efficient (single DELETE query)

---

## Best Practices

### Do

✅ Use fixtures for setup (`news_factory`, `cleanup_news`)  
✅ Test one behavior per test  
✅ Use descriptive test names  
✅ Add cleanup to `cleanup_news` list  
✅ Use strong assertions with messages  
✅ Test edge cases (NULL, empty, special characters)  

### Don't

❌ Leave test data in database  
❌ Use soft-delete (mark "DELETED")  
❌ Use weak assertions (`assert count >= 0`)  
❌ Create manual cleanup code  
❌ Skip `@pytest.mark.integration` marker  
❌ Test line coverage (that's for unit tests)  

---

## Writing New Tests

### Template

```python
import pytest
from data_platform.managers import PostgresManager

@pytest.mark.integration
class TestMyFeature:
    """Tests for my feature."""

    def test_my_behavior(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Test that my feature works correctly."""
        # Arrange
        news = news_factory(title="Test")
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Act
        result = postgres_manager.my_feature(news.unique_id)

        # Assert
        assert result is not None, "Feature should return result"
        assert result["status"] == "success"
```

### Add to conftest.py

If you need a fixture used by multiple tests:

```python
@pytest.fixture
def my_fixture(postgres_manager: PostgresManager) -> dict:
    """My reusable fixture."""
    # Setup
    data = {"key": "value"}
    yield data
    # Cleanup (if needed)
```

---

## CI/CD Integration

Integration tests are designed for CI/CD pipelines:

```yaml
# .github/workflows/test.yml
- name: Start Docker services
  run: docker-compose up -d

- name: Populate master data
  run: make populate-master

- name: Run integration tests
  run: make test-integration
```

---

## Related Documentation

- [Main README](../../README.md) - Project overview
- [Schema Documentation](../../_plan/SCHEMA.md) - Database schema details
- [CLAUDE.md](../../CLAUDE.md) - Development guidelines
- [Unit Tests](../unit/) - Unit test documentation

---

**Last Updated:** 2026-04-23  
**Test Count:** 60 integration tests  
**Success Rate:** 98.3%
