# Development Setup

Guide for setting up the development environment for the DestaquesGovBr Data Platform.

---

## Prerequisites

- Python 3.11+
- Poetry (or pip)
- Git
- Access to GCP project `inspire-7-finep`
- gcloud CLI configured

---

## Quick Start

```bash
# Clone repository
cd /path/to/destaquesgovbr/data-platform

# Install dependencies
poetry install

# Activate virtual environment
poetry shell

# Run tests
pytest

# Setup database (first time only)
./scripts/setup_database.sh
```

---

## Installation

### 1. Python Environment

**Option A: Poetry (recommended)**

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Activate virtual environment
poetry shell
```

**Option B: pip + venv**

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .
```

### 2. GCP Authentication

```bash
# Login to GCP
gcloud auth login
gcloud auth application-default login

# Set project
gcloud config set project inspire-7-finep

# Verify access to secrets
gcloud secrets versions access latest --secret="govbrnews-postgres-password"
```

### 3. Database Setup

```bash
# Install Cloud SQL Proxy
brew install cloud-sql-proxy  # macOS
# or download from https://cloud.google.com/sql/docs/postgres/connect-instance-auth-proxy

# Install PostgreSQL client
brew install postgresql@15

# Create database schema
./scripts/setup_database.sh
```

---

## Project Structure

```
data-platform/
├── docs/                   # Documentation
│   ├── database/          # Database schemas and migrations
│   ├── development/       # Development guides
│   └── architecture/      # Architecture docs
├── _plan/                 # Migration plan and progress
├── src/
│   └── data_platform/
│       ├── managers/      # Database managers (PostgresManager, etc)
│       ├── jobs/          # Data pipeline jobs
│       │   ├── scraper/
│       │   ├── enrichment/
│       │   └── hf_sync/
│       └── models/        # Data models
├── tests/
│   ├── unit/             # Unit tests
│   └── integration/      # Integration tests
├── scripts/              # Utility scripts
└── pyproject.toml        # Dependencies and config
```

---

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feat/my-feature
```

### 2. Make Changes

```python
# src/data_platform/managers/postgres_manager.py
class PostgresManager:
    def insert(self, data):
        # Your implementation
        pass
```

### 3. Write Tests

```python
# tests/unit/test_postgres_manager.py
def test_insert():
    manager = PostgresManager()
    result = manager.insert(sample_data)
    assert result > 0
```

### 4. Run Tests

```bash
# All tests
pytest

# Specific test file
pytest tests/unit/test_postgres_manager.py

# With coverage
pytest --cov=data_platform --cov-report=html

# Coverage report available at: htmlcov/index.html
```

### 5. Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff src/ tests/

# Type checking
mypy src/

# Or run all at once
black src/ tests/ && ruff src/ tests/ && mypy src/ && pytest
```

#### 5.1 Pre-Commit

The project has a [`.pre-commit-config.yaml`](/.pre-commit-config.yaml) file at the root, configured with hooks for formatting (`ruff-format`), linting (`ruff-check --fix`) and type checking (`mypy`).

**Install the git hooks** in the local repository. This is a **mandatory** step:

  ```bash
  pre-commit install
  ```


This configures git to run the hooks automatically before each commit.

### 6. Commit and Push

```bash
git add .
git commit -m "feat: implement PostgresManager.insert()"
git push origin feat/my-feature
```

---

## Running Tests

### Unit Tests

```bash
# All unit tests
pytest tests/unit/

# Specific test
pytest tests/unit/test_postgres_manager.py::test_insert

# With output
pytest -v tests/unit/

# Stop on first failure
pytest -x tests/unit/
```

### Integration Tests

```bash
# All integration tests (requires database)
pytest tests/integration/

# Skip integration tests
pytest tests/unit/
```

### Coverage

```bash
# Generate coverage report
pytest --cov=data_platform --cov-report=html

# View in browser
open htmlcov/index.html
```

---

## Database Development

### Connect to Database

```bash
# Start Cloud SQL Proxy
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &

# Get password
PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

# Connect
psql "host=127.0.0.1 dbname=govbrnews user=govbrnews_app password=$PASSWORD"
```

### Common SQL Queries

```sql
-- Check schema version
SELECT * FROM schema_version;

-- Count records
SELECT
    'agencies' as table, COUNT(*) as count FROM agencies
UNION ALL
SELECT 'themes', COUNT(*) FROM themes
UNION ALL
SELECT 'news', COUNT(*) FROM news;

-- Recent news
SELECT title, agency_name, published_at
FROM news
ORDER BY published_at DESC
LIMIT 10;

-- Check sync status
SELECT * FROM recent_syncs;
```

---

## Environment Variables

Create a `.env` file in the project root (ignored by git):

```bash
# .env
DATABASE_URL=postgresql://user:pass@host:5432/govbrnews
HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxx
TESTING=0
LOG_LEVEL=INFO
```

Load in Python:

```python
from dotenv import load_dotenv
import os

load_dotenv()

database_url = os.getenv("DATABASE_URL")
```

---

## Code Style

### Python Style Guide

- **Line length**: 100 characters
- **Formatter**: Black
- **Linter**: Ruff
- **Type hints**: Required for all functions
- **Docstrings**: Google style

### Example

```python
from typing import Optional
import pandas as pd


class PostgresManager:
    """Manages PostgreSQL database operations.

    Args:
        connection_string: PostgreSQL connection URI
        pool_size: Connection pool size (default: 5)

    Examples:
        >>> manager = PostgresManager(connection_string="postgresql://...")
        >>> manager.insert(data)
        42
    """

    def __init__(self, connection_string: str, pool_size: int = 5) -> None:
        self.connection_string = connection_string
        self.pool_size = pool_size

    def insert(self, data: dict) -> int:
        """Insert a single record.

        Args:
            data: Dictionary with record fields

        Returns:
            ID of inserted record

        Raises:
            ValueError: If required fields are missing
        """
        # Implementation
        return 42
```

---

## Debugging

### Enable Debug Logging

```python
from loguru import logger

logger.add("debug.log", level="DEBUG")
logger.debug("Detailed debug information")
```

### Interactive Debugging

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or use ipdb (install: pip install ipdb)
import ipdb; ipdb.set_trace()
```

### VS Code Launch Configuration

Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal",
      "env": {
        "PYTHONPATH": "${workspaceFolder}/src"
      }
    },
    {
      "name": "Python: Pytest",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["-v"],
      "console": "integratedTerminal"
    }
  ]
}
```

---

## Troubleshooting

### Import Errors

```bash
# Ensure src/ is in PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Or use poetry shell
poetry shell
```

### Database Connection Issues

```bash
# Check Cloud SQL Proxy is running
ps aux | grep cloud-sql-proxy

# Kill stale processes
lsof -ti:5432 | xargs kill -9

# Restart proxy
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres
```

### Test Failures

```bash
# Run with verbose output
pytest -vv tests/

# Show print statements
pytest -s tests/

# Run specific test with debugging
pytest --pdb tests/unit/test_postgres_manager.py::test_insert
```

---

## Useful Commands

```bash
# Update dependencies
poetry update

# Add new dependency
poetry add package-name

# Add dev dependency
poetry add --group dev package-name

# Show dependency tree
poetry show --tree

# Export requirements.txt
poetry export -f requirements.txt --output requirements.txt

# Clean cache
poetry cache clear pypi --all
```

---

See also:
- [Database Schema](../database/schema.md)
- [Database Migrations](../database/migrations.md)
- [Architecture Overview](../architecture/overview.md)
