# Typesense Repository Consolidation Migration Plan

> **Created**: 2025-12-27
> **Status**: Planning
> **Target Completion**: Q1 2025

## Executive Summary

This document outlines a comprehensive plan to consolidate the **Typesense repository** into the **data-platform repository**, creating a unified codebase for all data operations in the DestaquesGovBr ecosystem.

**Current State**: Two separate repositories with overlapping concerns
**Target State**: Single data-platform repository with integrated Typesense functionality
**Duration**: 3-4 weeks
**Risk Level**: Medium (requires coordination with MCP server and workflows)

---

## Table of Contents

1. [Rationale](#1-rationale)
2. [Scope](#2-scope)
3. [Repository Analysis](#3-repository-analysis)
4. [Migration Strategy](#4-migration-strategy)
5. [Detailed Migration Steps](#5-detailed-migration-steps)
6. [Workflow Consolidation](#6-workflow-consolidation)
7. [Testing Strategy](#7-testing-strategy)
8. [Deployment Plan](#8-deployment-plan)
9. [Rollback Plan](#9-rollback-plan)
10. [Risk Assessment](#10-risk-assessment)
11. [Success Criteria](#11-success-criteria)

---

## 1. Rationale

### Why Consolidate?

#### Current Architecture Issues

```
┌──────────────────────┐      ┌──────────────────────┐
│  typesense repo      │      │  data-platform repo  │
│  - MCP Server code   │      │  - Scrapers          │
│  - Typesense loader  │      │  - PostgreSQL        │
│  - Collection mgmt   │      │  - HF sync           │
│  - GH workflows      │      │  - Typesense sync*   │
└──────────────────────┘      └──────────────────────┘
         │                              │
         └──────── Both access ─────────┘
                Typesense Server
```

**Problem**: Duplicated concerns and split responsibility

#### Benefits of Consolidation

1. **Single Source of Truth**
   - All Typesense operations in one place
   - Unified schema management
   - Consistent versioning

2. **Simplified Dependencies**
   - No cross-repo dependencies
   - Single pyproject.toml
   - Easier dependency updates

3. **Streamlined CI/CD**
   - One workflow for data pipeline + Typesense
   - Atomic deployments
   - Reduced GitHub Actions complexity

4. **Better Code Organization**
   - Typesense as a "storage backend" alongside PostgreSQL
   - Unified storage adapter pattern
   - Clearer separation of concerns

5. **Improved Development Experience**
   - One repo to clone
   - Easier onboarding
   - Better IDE support

6. **MCP Server Integration**
   - MCP can depend on data-platform as library
   - No need to duplicate Typesense client code
   - Consistent collection schemas

#### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking MCP server | High | Keep MCP as separate repo, consume as library |
| Workflow conflicts | Medium | Careful merge of workflows |
| Import path changes | Medium | Gradual migration with deprecation warnings |
| Lost git history | Low | Preserve commits during migration |

---

## 2. Scope

### What to Migrate

#### Code Components

| Component | Source | Destination | Priority |
|-----------|--------|-------------|----------|
| **Core Library** | | | |
| `src/typesense_dgb/` | typesense | `src/data_platform/typesense/` | HIGH |
| `scripts/load_data.py` | typesense | `src/data_platform/jobs/typesense/` | HIGH |
| `scripts/delete_collection.py` | typesense | `src/data_platform/jobs/typesense/` | MEDIUM |
| `scripts/create_search_key.py` | typesense | `src/data_platform/jobs/typesense/` | LOW |
| **Docker** | | | |
| `Dockerfile` | typesense | `docker/typesense/Dockerfile` | HIGH |
| `entrypoint.sh` | typesense | `docker/typesense/entrypoint.sh` | HIGH |
| `run-typesense-server.sh` | typesense | `scripts/run-typesense-server.sh` | MEDIUM |
| **Workflows** | | | |
| `.github/workflows/docker-build-push.yml` | typesense | Merge into `docker-build.yaml` | HIGH |
| `.github/workflows/typesense-daily-load.yml` | typesense | Merge into `main-workflow.yaml` | HIGH |
| `.github/workflows/typesense-full-reload.yml` | typesense | Merge into `main-workflow.yaml` | MEDIUM |
| **Tests** | | | |
| `test_init_typesense.py` | typesense | `tests/integration/test_typesense_loader.py` | MEDIUM |
| **Documentation** | | | |
| `README.md` | typesense | `docs/typesense/README.md` | HIGH |
| `docs/` | typesense | `docs/typesense/` | MEDIUM |

#### What to Keep Separate

| Component | Location | Reason |
|-----------|----------|--------|
| **MCP Server** | `/govbrnews-mcp/` (separate) | Different deployment model, can consume data-platform as library |
| **Web UI** | `typesense/web-ui/` → Archive | Standalone, not used in production |

#### What to Deprecate

| Component | Reason |
|-----------|--------|
| `init-typesense.py` (root) | Replaced by modular job structure |
| `requirements.txt` | Using pyproject.toml |
| Various documentation files | Consolidate into unified docs |

---

## 3. Repository Analysis

### Typesense Repository Structure

```
typesense/
├── src/typesense_dgb/              # Core library (MIGRATE)
│   ├── __init__.py                 # Exports
│   ├── client.py                   # Typesense client wrapper
│   ├── collection.py               # Schema & collection management
│   ├── dataset.py                  # HuggingFace dataset loader
│   ├── indexer.py                  # Document indexing
│   └── utils.py                    # Utilities
├── scripts/                        # CLI scripts (MIGRATE)
│   ├── load_data.py                # Main loader
│   ├── delete_collection.py        # Collection deletion
│   └── create_search_key.py        # API key generation
├── .github/workflows/              # Workflows (MERGE)
│   ├── docker-build-push.yml       # Docker build
│   ├── typesense-daily-load.yml    # Daily incremental
│   └── typesense-full-reload.yml   # Full reload
├── Dockerfile                      # Docker image (MIGRATE)
├── entrypoint.sh                   # Docker entrypoint (MIGRATE)
├── pyproject.toml                  # Dependencies (MERGE)
└── docs/                           # Documentation (MIGRATE)
```

**Lines of Code**: ~2,500 Python
**Dependencies**: datasets, pandas, typesense, huggingface_hub
**External Integrations**: Typesense server, HuggingFace

### Data-Platform Repository Structure

```
data-platform/
├── src/data_platform/
│   ├── managers/                   # Storage backends
│   │   ├── postgres_manager.py     # PostgreSQL
│   │   ├── dataset_manager.py      # HuggingFace
│   │   └── storage_adapter.py      # Unified interface
│   ├── jobs/
│   │   ├── embeddings/             # Embedding generation
│   │   │   └── typesense_sync.py   # ALREADY EXISTS (sync embeddings)
│   │   └── hf_sync/                # HuggingFace sync
│   ├── scrapers/                   # Web scrapers
│   ├── cogfy/                      # AI enrichment
│   └── models/                     # Pydantic models
├── .github/workflows/
│   ├── main-workflow.yaml          # Daily pipeline
│   ├── pipeline-steps.yaml         # Pipeline jobs
│   └── docker-build.yaml           # Docker build
├── scripts/                        # Migration scripts
└── docs/                           # Documentation
```

**Lines of Code**: ~8,000 Python
**Dependencies**: psycopg2, sqlalchemy, datasets, pandas, typesense, sentence-transformers

### Overlap Analysis

| Functionality | Typesense Repo | Data-Platform Repo |
|---------------|----------------|-------------------|
| **Typesense Client** | `client.py` (full) | `typesense_sync.py` (basic) |
| **Collection Schema** | `collection.py` (comprehensive) | `typesense_sync.py` (partial) |
| **Data Indexing** | `indexer.py` (full) | `typesense_sync.py` (embeddings only) |
| **Dataset Loading** | `dataset.py` (HF) | N/A |
| **Docker Image** | `Dockerfile` (Typesense-based) | `Dockerfile` (Python-based) |

**Conclusion**: Minimal overlap; data-platform has only embedding sync, Typesense repo has full loader.

---

## 4. Migration Strategy

### Principles

1. **Preserve Git History**: Use `git mv` and proper merge strategies
2. **Gradual Migration**: Move components incrementally, not all at once
3. **Backward Compatibility**: Maintain import paths during transition
4. **Test at Each Step**: Validate after each component migration
5. **Separate PRs**: Each phase gets its own PR for review

### Target Structure

```
data-platform/
├── src/data_platform/
│   ├── typesense/                      # ← NEW: Consolidated module
│   │   ├── __init__.py                 # Public API exports
│   │   ├── client.py                   # Typesense client (from typesense_dgb)
│   │   ├── collection.py               # Schema & management
│   │   ├── indexer.py                  # Document indexing
│   │   ├── dataset_loader.py           # HuggingFace loader (renamed)
│   │   └── utils.py                    # Utilities
│   ├── managers/
│   │   ├── postgres_manager.py
│   │   ├── dataset_manager.py
│   │   ├── storage_adapter.py
│   │   └── typesense_manager.py        # ← NEW: Storage interface
│   ├── jobs/
│   │   ├── typesense/                  # ← NEW: Typesense jobs
│   │   │   ├── __init__.py
│   │   │   ├── full_load.py            # Full reload job
│   │   │   ├── incremental_load.py     # Daily incremental
│   │   │   └── collection_manager.py   # Collection ops
│   │   ├── embeddings/
│   │   │   ├── embedding_generator.py
│   │   │   └── typesense_sync.py       # Keep for embeddings
│   │   └── hf_sync/
│   └── cli.py                          # Add typesense commands
├── docker/
│   └── typesense/                      # ← NEW: Typesense Docker
│       ├── Dockerfile
│       └── entrypoint.sh
├── scripts/
│   └── run-typesense-server.sh         # ← Moved from root
├── tests/
│   ├── unit/
│   │   └── test_typesense_client.py    # ← NEW
│   └── integration/
│       └── test_typesense_loader.py    # ← NEW
└── docs/
    └── typesense/                      # ← NEW: Typesense docs
        ├── README.md
        ├── architecture.md
        └── mcp-integration.md
```

### Import Path Migration

**Old Paths** (typesense repo):
```python
from typesense_dgb import get_client, create_collection
from typesense_dgb.indexer import index_documents
```

**New Paths** (data-platform):
```python
from data_platform.typesense import get_client, create_collection
from data_platform.typesense.indexer import index_documents
```

**MCP Server Adaptation** (govbrnews-mcp repo):
```python
# Before (direct client)
import typesense
client = typesense.Client(...)

# After (use data-platform)
from data_platform.typesense import get_client
client = get_client()
```

---

## 5. Detailed Migration Steps

### Phase 1: Preparation (Week 1)

#### 1.1 Create Branch Strategy

```bash
# In data-platform repo
git checkout -b migrate/typesense-consolidation

# Create sub-branches for each phase
git checkout -b migrate/typesense-phase1-core
```

#### 1.2 Preserve Git History

```bash
# Clone typesense repo to extract history
cd /tmp
git clone /path/to/typesense typesense-history

# Extract subtree with history
git filter-branch --prune-empty --subdirectory-filter src/typesense_dgb HEAD

# Prepare patch files
git format-patch --root --output-directory=/tmp/typesense-patches
```

#### 1.3 Create Directory Structure

```bash
cd /path/to/data-platform

# Create new directories
mkdir -p src/data_platform/typesense
mkdir -p src/data_platform/jobs/typesense
mkdir -p docker/typesense
mkdir -p docs/typesense
mkdir -p tests/unit/typesense
mkdir -p tests/integration/typesense
```

#### 1.4 Update pyproject.toml

**Add Typesense Dependencies**:

```toml
[tool.poetry.dependencies]
# Existing dependencies...

# Typesense (from typesense repo)
typesense = ">=0.21.0"

# Already have:
# datasets = ">=3.1.0"
# pandas = ">=2.1.4"
# huggingface-hub = ">=0.20.0"
```

**Add CLI Scripts**:

```toml
[tool.poetry.scripts]
data-platform = "data_platform.cli:app"

# Legacy compatibility (temporary)
typesense-load = "data_platform.typesense.cli:load_data"
typesense-delete = "data_platform.typesense.cli:delete_collection"
```

#### Checklist

- [ ] Create migration branches
- [ ] Extract git history from typesense repo
- [ ] Create directory structure in data-platform
- [ ] Update pyproject.toml with dependencies
- [ ] Run `poetry lock` and verify no conflicts
- [ ] Commit structure changes

---

### Phase 2: Core Library Migration (Week 1-2)

#### 2.1 Migrate Core Modules

**Copy with History Preservation**:

```bash
# Method: Use git subtree merge to preserve history
cd /path/to/data-platform

# Add typesense repo as remote
git remote add typesense-source /path/to/typesense

# Fetch
git fetch typesense-source

# Merge specific paths
git read-tree --prefix=src/data_platform/typesense/ -u typesense-source/main:src/typesense_dgb
```

**Files to Migrate**:

| Source | Destination | Changes Needed |
|--------|-------------|----------------|
| `src/typesense_dgb/__init__.py` | `src/data_platform/typesense/__init__.py` | Update imports |
| `src/typesense_dgb/client.py` | `src/data_platform/typesense/client.py` | None |
| `src/typesense_dgb/collection.py` | `src/data_platform/typesense/collection.py` | None |
| `src/typesense_dgb/dataset.py` | `src/data_platform/typesense/dataset_loader.py` | Rename |
| `src/typesense_dgb/indexer.py` | `src/data_platform/typesense/indexer.py` | None |
| `src/typesense_dgb/utils.py` | `src/data_platform/typesense/utils.py` | None |

#### 2.2 Update Imports

**In `src/data_platform/typesense/__init__.py`**:

```python
"""
Typesense integration for DestaquesGovBr.

Migrated from typesense repository on 2025-12-27.
"""

from data_platform.typesense.client import get_client, wait_for_typesense
from data_platform.typesense.collection import (
    COLLECTION_NAME,
    COLLECTION_SCHEMA,
    create_collection,
    delete_collection,
    list_collections,
)
from data_platform.typesense.dataset_loader import download_and_process_dataset
from data_platform.typesense.indexer import index_documents, prepare_document
from data_platform.typesense.utils import calculate_published_week

__version__ = "2.0.0"  # Bumped for migration
__all__ = [
    # Client
    "get_client",
    "wait_for_typesense",
    # Collection
    "COLLECTION_NAME",
    "COLLECTION_SCHEMA",
    "create_collection",
    "delete_collection",
    "list_collections",
    # Dataset
    "download_and_process_dataset",
    # Indexer
    "index_documents",
    "prepare_document",
    # Utils
    "calculate_published_week",
]
```

**In each module**: Update internal imports to use `data_platform.typesense.*`

#### 2.3 Create TypesenseManager

**New file**: `src/data_platform/managers/typesense_manager.py`

```python
"""
TypesenseManager - Storage interface for Typesense.

Implements the same interface as PostgresManager and DatasetManager
for use with StorageAdapter.
"""

from collections import OrderedDict
from datetime import datetime
from typing import Optional

import pandas as pd

from data_platform.typesense import (
    get_client,
    create_collection,
    index_documents,
    download_and_process_dataset,
)


class TypesenseManager:
    """
    Manages Typesense as a storage backend.

    Provides compatible interface with PostgresManager and DatasetManager.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize Typesense manager."""
        self.client = get_client(host=host, port=port, api_key=api_key)
        create_collection(self.client)

    def insert(self, new_data: OrderedDict, allow_update: bool = False) -> int:
        """
        Insert news records into Typesense.

        Args:
            new_data: OrderedDict with news data
            allow_update: If True, performs upsert

        Returns:
            Number of records indexed
        """
        # Convert OrderedDict to DataFrame
        df = pd.DataFrame(new_data)

        # Index documents
        stats = index_documents(
            self.client,
            df,
            mode="incremental" if allow_update else "full",
            force=allow_update,
        )

        return stats.get("total_indexed", 0)

    def get(
        self,
        min_date: str,
        max_date: str,
        agency: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get news records from Typesense.

        Note: Typesense is optimized for search, not for bulk retrieval.
        This method is primarily for compatibility; prefer PostgreSQL for this.

        Args:
            min_date: Start date (YYYY-MM-DD)
            max_date: End date (YYYY-MM-DD)
            agency: Filter by agency (optional)

        Returns:
            DataFrame with news records
        """
        # Build filter
        filters = []

        # Date range
        min_ts = int(pd.Timestamp(min_date).timestamp())
        max_ts = int(pd.Timestamp(max_date).timestamp())
        filters.append(f"published_at:>={min_ts}")
        filters.append(f"published_at:<={max_ts}")

        # Agency
        if agency:
            filters.append(f"agency:={agency}")

        # Search (get all)
        search_params = {
            "q": "*",
            "query_by": "title",
            "filter_by": " && ".join(filters),
            "per_page": 250,  # Max per page
        }

        results = self.client.collections["news"].documents.search(search_params)

        # Convert to DataFrame
        records = [hit["document"] for hit in results.get("hits", [])]
        return pd.DataFrame(records)
```

#### 2.4 Add to StorageAdapter

**Update**: `src/data_platform/managers/storage_adapter.py`

```python
class StorageBackend(Enum):
    HUGGINGFACE = "huggingface"
    POSTGRES = "postgres"
    TYPESENSE = "typesense"  # ← NEW
    DUAL_WRITE = "dual_write"

# ...

def _init_storage(self):
    """Initialize storage backends based on configuration."""
    # ...

    if self.backend in (StorageBackend.TYPESENSE, StorageBackend.DUAL_WRITE):
        from data_platform.managers.typesense_manager import TypesenseManager
        self.typesense = TypesenseManager()
```

#### Checklist

- [ ] Migrate core modules from typesense repo
- [ ] Update all internal imports
- [ ] Create TypesenseManager
- [ ] Integrate with StorageAdapter
- [ ] Run unit tests
- [ ] Update documentation

---

### Phase 3: Jobs Migration (Week 2)

#### 3.1 Migrate Load Scripts

**Create**: `src/data_platform/jobs/typesense/full_load.py`

**Migrate from**: `typesense/scripts/load_data.py`

**Changes**:
- Update imports to use `data_platform.typesense.*`
- Remove CLI parsing (moved to main CLI)
- Return statistics for monitoring

```python
"""
Full load job for Typesense.

Loads entire dataset from HuggingFace to Typesense.
"""

import logging
from typing import Dict, Optional

from data_platform.typesense import (
    get_client,
    wait_for_typesense,
    create_collection,
    download_and_process_dataset,
    index_documents,
)
from data_platform.typesense.indexer import run_test_queries

logger = logging.getLogger(__name__)


def run_full_load(
    mode: str = "full",
    days: int = 7,
    force: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """
    Run full load of Typesense from HuggingFace.

    Args:
        mode: 'full' or 'incremental'
        days: Days to look back (incremental mode)
        force: Force full load even if collection exists
        limit: Limit number of records (testing)

    Returns:
        Statistics dict with counts
    """
    logger.info(f"Starting Typesense load: mode={mode}, force={force}")

    # Connect to Typesense
    client = wait_for_typesense()
    if not client:
        raise RuntimeError("Failed to connect to Typesense")

    # Create collection
    create_collection(client)

    # Download dataset
    df = download_and_process_dataset(
        mode=mode,
        days=days,
        limit=limit,
    )

    # Index documents
    stats = index_documents(
        client,
        df,
        mode=mode,
        force=force,
    )

    # Run test queries
    run_test_queries(client)

    logger.info(f"Load complete: {stats}")
    return stats
```

**Create**: `src/data_platform/jobs/typesense/incremental_load.py`

```python
"""
Incremental load job for Typesense.

Loads recent news (last N days) from HuggingFace.
"""

from typing import Dict, Optional
from data_platform.jobs.typesense.full_load import run_full_load


def run_incremental_load(days: int = 7, limit: Optional[int] = None) -> Dict[str, int]:
    """
    Run incremental load for last N days.

    Args:
        days: Number of days to look back
        limit: Limit records (testing)

    Returns:
        Statistics dict
    """
    return run_full_load(
        mode="incremental",
        days=days,
        force=False,
        limit=limit,
    )
```

**Create**: `src/data_platform/jobs/typesense/collection_manager.py`

**Migrate from**: `typesense/scripts/delete_collection.py`

```python
"""
Collection management jobs for Typesense.
"""

import logging
from typing import Dict, List

from data_platform.typesense import get_client, delete_collection, list_collections

logger = logging.getLogger(__name__)


def delete_news_collection(confirm: bool = False) -> bool:
    """
    Delete news collection from Typesense.

    Args:
        confirm: Skip confirmation prompt

    Returns:
        True if deleted successfully
    """
    client = get_client()
    return delete_collection(client, confirm=confirm)


def list_all_collections() -> List[Dict]:
    """
    List all Typesense collections.

    Returns:
        List of collection info dicts
    """
    client = get_client()
    return list_collections(client)
```

#### 3.2 Update CLI

**Add to**: `src/data_platform/cli.py`

```python
# Typesense commands
@app.command()
def typesense_load(
    mode: str = typer.Option("full", help="Load mode: full or incremental"),
    days: int = typer.Option(7, help="Days to look back (incremental mode)"),
    force: bool = typer.Option(False, help="Force load even if collection exists"),
    limit: int = typer.Option(None, help="Limit records (testing)"),
):
    """Load HuggingFace data into Typesense."""
    from data_platform.jobs.typesense.full_load import run_full_load

    stats = run_full_load(mode=mode, days=days, force=force, limit=limit)
    typer.echo(f"Load complete: {stats['total_indexed']} documents indexed")


@app.command()
def typesense_delete(
    confirm: bool = typer.Option(False, help="Skip confirmation prompt"),
):
    """Delete Typesense news collection."""
    from data_platform.jobs.typesense.collection_manager import delete_news_collection

    if delete_news_collection(confirm=confirm):
        typer.echo("Collection deleted successfully")
    else:
        typer.echo("Collection deletion failed", err=True)


@app.command()
def typesense_list():
    """List all Typesense collections."""
    from data_platform.jobs.typesense.collection_manager import list_all_collections

    collections = list_all_collections()
    for col in collections:
        typer.echo(f"{col['name']}: {col['num_documents']} documents")
```

**Usage**:

```bash
# Full load
data-platform typesense-load --mode full --force

# Incremental (last 7 days)
data-platform typesense-load --mode incremental --days 7

# Delete collection
data-platform typesense-delete --confirm

# List collections
data-platform typesense-list
```

#### Checklist

- [ ] Create full_load.py job
- [ ] Create incremental_load.py job
- [ ] Create collection_manager.py
- [ ] Add CLI commands
- [ ] Test CLI locally
- [ ] Update documentation

---

### Phase 4: Docker Migration (Week 2)

#### 4.1 Migrate Dockerfile

**Create**: `docker/typesense/Dockerfile`

**Migrate from**: `typesense/Dockerfile`

**Changes**:
- Use data-platform package instead of typesense_dgb
- Update PYTHONPATH
- Install data-platform with all extras

```dockerfile
# Typesense with Data Platform Integration
FROM typesense/typesense:27.1

# Install Python and build dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app directory
WORKDIR /app

# Copy data-platform package
COPY pyproject.toml poetry.lock /app/
COPY src/ /app/src/

# Install data-platform with all dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi

# Copy entrypoint
COPY docker/typesense/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

# Environment variables
ENV TYPESENSE_DATA_DIR=/data
ENV PYTHONPATH=/app/src

# Create data directory
RUN mkdir -p /data

# Expose Typesense port
EXPOSE 8108

# Use custom entrypoint
ENTRYPOINT ["/opt/entrypoint.sh"]
```

#### 4.2 Migrate Entrypoint

**Create**: `docker/typesense/entrypoint.sh`

**Migrate from**: `typesense/entrypoint.sh`

**Changes**:
- Use data-platform CLI instead of init script
- Update Python paths

```bash
#!/bin/bash
set -e

echo "Starting Typesense server with data-platform integration..."

# Start Typesense server in background
/opt/typesense-server \
  --data-dir="${TYPESENSE_DATA_DIR}" \
  --api-key="${TYPESENSE_API_KEY}" \
  --enable-cors &

TYPESENSE_PID=$!
echo "Typesense server started (PID: $TYPESENSE_PID)"

# Wait for Typesense to be ready
echo "Waiting for Typesense to be ready..."
max_attempts=30
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localhost:8108/health > /dev/null 2>&1; then
        echo "Typesense is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "Attempt $attempt/$max_attempts..."
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "ERROR: Typesense failed to start"
    exit 1
fi

# Check if data already exists
if [ -f "${TYPESENSE_DATA_DIR}/state/db/CURRENT" ]; then
    echo "Typesense data already exists, skipping initialization"
else
    echo "No existing data found, running initialization..."

    # Run data-platform CLI to load data
    data-platform typesense-load --mode full --force

    if [ $? -eq 0 ]; then
        echo "Initialization completed successfully"
    else
        echo "ERROR: Initialization failed"
        exit 1
    fi
fi

# Keep container running
echo "Setup complete. Typesense is running on port 8108"
wait $TYPESENSE_PID
```

#### 4.3 Update Docker Build Workflow

**Modify**: `.github/workflows/docker-build.yaml`

**Add Typesense image build**:

```yaml
name: Build Docker Images

on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'docker/**'
      - 'pyproject.toml'
  workflow_dispatch:

env:
  REGION: southamerica-east1
  PROJECT_ID: inspire-7-finep
  REPOSITORY: data-platform

jobs:
  # Existing job for main data-platform image
  build-main:
    name: Build Main Image
    runs-on: ubuntu-latest
    # ... existing configuration ...

  # NEW: Build Typesense image
  build-typesense:
    name: Build Typesense Image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}

      - name: Configure Docker for Artifact Registry
        run: gcloud auth configure-docker ${{ env.REGION }}-docker.pkg.dev --quiet

      - name: Build Typesense Docker image
        run: |
          docker build \
            -f docker/typesense/Dockerfile \
            -t ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/${{ env.REPOSITORY }}/typesense:latest \
            -t ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/${{ env.REPOSITORY }}/typesense:${{ github.sha }} \
            .

      - name: Push to Artifact Registry
        run: |
          docker push ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/${{ env.REPOSITORY }}/typesense:latest
          docker push ${{ env.REGION }}-docker.pkg.dev/${{ env.PROJECT_ID }}/${{ env.REPOSITORY }}/typesense:${{ github.sha }}

      - name: Summary
        run: |
          echo "## Typesense Image Published" >> $GITHUB_STEP_SUMMARY
          echo "**Image:** \`typesense:latest\`" >> $GITHUB_STEP_SUMMARY
          echo "**SHA:** \`${{ github.sha }}\`" >> $GITHUB_STEP_SUMMARY
```

#### Checklist

- [ ] Create docker/typesense/Dockerfile
- [ ] Create docker/typesense/entrypoint.sh
- [ ] Test Docker build locally
- [ ] Update docker-build.yaml workflow
- [ ] Test Docker image with full load
- [ ] Update documentation

---

### Phase 5: Workflow Migration (Week 3)

#### 5.1 Merge Daily Load Workflow

**Modify**: `.github/workflows/main-workflow.yaml`

**Add Typesense incremental load job** (after embedding jobs):

```yaml
jobs:
  # ... existing jobs ...

  # NEW: Typesense Incremental Load
  typesense-incremental:
    name: Typesense Incremental Load
    runs-on: ubuntu-latest
    needs: [sync-embeddings-to-typesense]  # Run after embeddings sync
    permissions:
      contents: read
      id-token: write

    steps:
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}

      - name: Fetch Typesense Config
        id: typesense
        uses: destaquesgovbr/reusable-workflows/actions/fetch-typesense-config@v1
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}
          secret_name: typesense-write-conn

      - name: Run incremental load
        run: |
          docker run --rm \
            -e TYPESENSE_HOST=${{ steps.typesense.outputs.host }} \
            -e TYPESENSE_PORT=${{ steps.typesense.outputs.port }} \
            -e TYPESENSE_API_KEY=${{ steps.typesense.outputs.api_key }} \
            -e HF_TOKEN=${{ secrets.HF_TOKEN }} \
            ghcr.io/destaquesgovbr/data-platform/typesense:latest \
            data-platform typesense-load --mode incremental --days 7

      - name: Report status
        if: always()
        run: |
          if [ ${{ job.status }} == 'success' ]; then
            echo "✅ Typesense incremental load completed"
          else
            echo "❌ Typesense incremental load failed"
            exit 1
          fi
```

#### 5.2 Add Full Reload Workflow

**Create**: `.github/workflows/typesense-full-reload.yaml`

**Migrate from**: `typesense/.github/workflows/typesense-full-reload.yml`

**Changes**:
- Use data-platform Docker image
- Use data-platform CLI
- Integrate with new infrastructure

```yaml
name: Typesense Full Reload

on:
  workflow_dispatch:
    inputs:
      confirm_deletion:
        description: 'Type "DELETE" to confirm collection deletion and full reload'
        required: true
        type: string

env:
  REGION: southamerica-east1
  PROJECT_ID: inspire-7-finep
  COLLECTION_NAME: 'news'

jobs:
  full-reload:
    name: Delete Collection and Reload All Data
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write

    steps:
      - name: Validate confirmation
        run: |
          if [ "${{ github.event.inputs.confirm_deletion }}" != "DELETE" ]; then
            echo "❌ Confirmation failed. Type 'DELETE' to proceed."
            exit 1
          fi
          echo "✅ Confirmation validated"

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}

      - name: Fetch Typesense Config
        id: typesense
        uses: destaquesgovbr/reusable-workflows/actions/fetch-typesense-config@v1
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}
          secret_name: typesense-write-conn

      - name: Delete existing collection
        continue-on-error: true
        run: |
          docker run --rm \
            -e TYPESENSE_HOST=${{ steps.typesense.outputs.host }} \
            -e TYPESENSE_PORT=${{ steps.typesense.outputs.port }} \
            -e TYPESENSE_API_KEY=${{ steps.typesense.outputs.api_key }} \
            ghcr.io/destaquesgovbr/data-platform/typesense:latest \
            data-platform typesense-delete --confirm

      - name: Run full reload
        run: |
          docker run --rm \
            -e TYPESENSE_HOST=${{ steps.typesense.outputs.host }} \
            -e TYPESENSE_PORT=${{ steps.typesense.outputs.port }} \
            -e TYPESENSE_API_KEY=${{ steps.typesense.outputs.api_key }} \
            -e HF_TOKEN=${{ secrets.HF_TOKEN }} \
            ghcr.io/destaquesgovbr/data-platform/typesense:latest \
            data-platform typesense-load --mode full --force

      - name: Verify collection
        run: |
          docker run --rm \
            -e TYPESENSE_HOST=${{ steps.typesense.outputs.host }} \
            -e TYPESENSE_PORT=${{ steps.typesense.outputs.port }} \
            -e TYPESENSE_API_KEY=${{ steps.typesense.outputs.api_key }} \
            ghcr.io/destaquesgovbr/data-platform/typesense:latest \
            data-platform typesense-list

      - name: Report status
        if: always()
        run: |
          if [ ${{ job.status }} == 'success' ]; then
            echo "✅ Full reload completed successfully"
          else
            echo "❌ Full reload failed"
            exit 1
          fi
```

#### 5.3 Workflow Consolidation Matrix

| Workflow (Typesense) | Status | Consolidation Target | Action |
|---------------------|--------|---------------------|--------|
| `docker-build-push.yml` | Migrate | `docker-build.yaml` | Add typesense image build job |
| `typesense-daily-load.yml` | Merge | `main-workflow.yaml` | Add incremental load job |
| `typesense-full-reload.yml` | Keep Separate | New workflow file | Standalone manual trigger |
| `test-local.yml` | Deprecate | N/A | Not needed (use pytest) |

#### Checklist

- [ ] Add typesense-incremental job to main-workflow
- [ ] Create typesense-full-reload workflow
- [ ] Test workflow with manual trigger
- [ ] Update workflow documentation
- [ ] Archive old typesense workflows

---

### Phase 6: Testing & Validation (Week 3)

#### 6.1 Unit Tests

**Create**: `tests/unit/typesense/test_client.py`

```python
"""Unit tests for Typesense client."""

import pytest
from data_platform.typesense import get_client, wait_for_typesense


def test_get_client_defaults(monkeypatch):
    """Test client creation with default values."""
    monkeypatch.setenv("TYPESENSE_HOST", "localhost")
    monkeypatch.setenv("TYPESENSE_PORT", "8108")
    monkeypatch.setenv("TYPESENSE_API_KEY", "test-key")

    client = get_client()

    assert client is not None
    assert client.config["nodes"][0]["host"] == "localhost"
    assert client.config["nodes"][0]["port"] == "8108"


def test_get_client_custom_params():
    """Test client with custom parameters."""
    client = get_client(
        host="custom-host",
        port="9999",
        api_key="custom-key",
    )

    assert client.config["nodes"][0]["host"] == "custom-host"
    assert client.config["nodes"][0]["port"] == "9999"
    assert client.config["api_key"] == "custom-key"
```

**Create**: `tests/unit/typesense/test_collection.py`

```python
"""Unit tests for Typesense collection management."""

import pytest
from unittest.mock import Mock, patch
from data_platform.typesense import create_collection, delete_collection, COLLECTION_SCHEMA


def test_collection_schema_structure():
    """Test collection schema is valid."""
    assert COLLECTION_SCHEMA["name"] == "news"
    assert "fields" in COLLECTION_SCHEMA
    assert len(COLLECTION_SCHEMA["fields"]) > 10

    # Check required fields
    field_names = [f["name"] for f in COLLECTION_SCHEMA["fields"]]
    assert "unique_id" in field_names
    assert "published_at" in field_names
    assert "title" in field_names


@patch("data_platform.typesense.collection.typesense.Client")
def test_create_collection_new(mock_client):
    """Test creating new collection."""
    client = Mock()
    client.collections.__getitem__.return_value.retrieve.side_effect = \
        Exception("Not found")

    result = create_collection(client)

    assert result is True
    client.collections.create.assert_called_once()
```

**Create**: `tests/unit/typesense/test_indexer.py`

```python
"""Unit tests for Typesense indexer."""

import pytest
import pandas as pd
from data_platform.typesense.indexer import prepare_document, clean_tags


def test_prepare_document_basic():
    """Test basic document preparation."""
    row = pd.Series({
        "unique_id": "test-123",
        "title": "Test News",
        "published_at_ts": 1704067200,  # 2024-01-01
        "agency": "Test Agency",
    })

    doc = prepare_document(row)

    assert doc["unique_id"] == "test-123"
    assert doc["title"] == "Test News"
    assert doc["published_at"] == 1704067200
    assert doc["agency"] == "Test Agency"


def test_clean_tags_valid():
    """Test tag cleaning with valid tags."""
    tags = ["educação", "saúde", "tecnologia"]

    cleaned = clean_tags(tags)

    assert len(cleaned) == 3
    assert "educação" in cleaned


def test_clean_tags_filters_long():
    """Test filtering of overly long tags."""
    tags = ["short", "x" * 150]  # Second tag too long

    cleaned = clean_tags(tags)

    assert len(cleaned) == 1
    assert "short" in cleaned
```

#### 6.2 Integration Tests

**Create**: `tests/integration/test_typesense_loader.py`

```python
"""Integration tests for Typesense loader."""

import pytest
import os
from data_platform.jobs.typesense.full_load import run_full_load


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("TYPESENSE_HOST"),
    reason="Requires Typesense server",
)
def test_full_load_small_dataset():
    """Test full load with small dataset."""
    stats = run_full_load(
        mode="incremental",
        days=1,
        limit=10,  # Only 10 records for testing
    )

    assert stats["total_processed"] == 10
    assert stats["total_indexed"] <= 10
    assert stats["errors"] == 0


@pytest.mark.integration
def test_incremental_load():
    """Test incremental load."""
    from data_platform.jobs.typesense.incremental_load import run_incremental_load

    stats = run_incremental_load(days=7, limit=50)

    assert stats["total_processed"] > 0
    assert stats["total_indexed"] > 0
```

#### 6.3 Test Execution Plan

**Local Testing**:

```bash
# 1. Unit tests (no external dependencies)
poetry run pytest tests/unit/typesense/ -v

# 2. Integration tests (requires Typesense)
docker run -d --name typesense-test \
  -p 8108:8108 \
  typesense/typesense:27.1 \
  --data-dir=/data --api-key=test-key

export TYPESENSE_HOST=localhost
export TYPESENSE_PORT=8108
export TYPESENSE_API_KEY=test-key

poetry run pytest tests/integration/test_typesense_loader.py -v -m integration

# 3. Full workflow test
poetry run data-platform typesense-load --mode incremental --days 1 --limit 100

# Cleanup
docker stop typesense-test && docker rm typesense-test
```

**CI Testing** (add to `.github/workflows/test.yaml`):

```yaml
jobs:
  test-typesense:
    name: Test Typesense Integration
    runs-on: ubuntu-latest

    services:
      typesense:
        image: typesense/typesense:27.1
        env:
          TYPESENSE_API_KEY: test-key
        options: >-
          --health-cmd="curl -f http://localhost:8108/health"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install poetry
          poetry install

      - name: Run Typesense tests
        env:
          TYPESENSE_HOST: typesense
          TYPESENSE_PORT: 8108
          TYPESENSE_API_KEY: test-key
        run: |
          poetry run pytest tests/unit/typesense/ -v
          poetry run pytest tests/integration/test_typesense_loader.py -v -m integration
```

#### Checklist

- [ ] Create unit tests for client, collection, indexer
- [ ] Create integration tests for loader
- [ ] Test locally with Docker Typesense
- [ ] Add CI workflow for testing
- [ ] Achieve >80% code coverage
- [ ] Document test procedures

---

### Phase 7: Documentation & Cleanup (Week 4)

#### 7.1 Migrate Documentation

**Create**: `docs/typesense/README.md`

**Migrate from**: `typesense/README.md`

**Updates**:
- Update all import paths
- Update CLI commands
- Reference data-platform structure
- Add migration notes

**Create**: `docs/typesense/architecture.md`

```markdown
# Typesense Architecture in Data Platform

## Overview

Typesense is integrated into data-platform as a storage backend and search engine
for the DestaquesGovBr news dataset.

## Components

### 1. Core Library (`src/data_platform/typesense/`)

- **client.py**: Typesense client wrapper
- **collection.py**: Schema and collection management
- **indexer.py**: Document indexing logic
- **dataset_loader.py**: HuggingFace dataset integration

### 2. Storage Manager (`src/data_platform/managers/typesense_manager.py`)

Implements the storage interface for compatibility with PostgreSQL and HuggingFace
backends.

### 3. Jobs (`src/data_platform/jobs/typesense/`)

- **full_load.py**: Full dataset load from HuggingFace
- **incremental_load.py**: Daily incremental updates
- **collection_manager.py**: Collection operations (delete, list)

### 4. Docker Image (`docker/typesense/`)

Self-contained image with Typesense server + data-platform loader.

## Data Flow

```
HuggingFace Dataset
        ↓
  dataset_loader.py
        ↓
    indexer.py
        ↓
 Typesense Server
        ↓
   MCP Server (Claude)
```

## Integration Points

### With PostgreSQL
- Embeddings sync: PostgreSQL → Typesense
- Shared data models

### With MCP Server
- MCP depends on data-platform package
- Uses same collection schema
- Direct Typesense client access

### With Workflows
- Daily incremental load after embeddings
- Manual full reload workflow
- Docker image build on push
```

**Create**: `docs/typesense/mcp-integration.md`

```markdown
# MCP Server Integration

## Overview

The MCP server (`govbrnews-mcp`) provides conversational access to Typesense
data for Claude Desktop.

## Architecture

```
Claude Desktop
    ↓ (MCP Protocol)
govbrnews-mcp server
    ↓ (imports)
data_platform.typesense
    ↓ (Typesense SDK)
Typesense Server
```

## Migration Impact

### Before Consolidation

```python
# MCP Server (govbrnews-mcp)
import typesense

client = typesense.Client(config)
```

### After Consolidation

```python
# MCP Server (govbrnews-mcp)
from data_platform.typesense import get_client

client = get_client()
```

## Update Steps for MCP

1. Add data-platform as dependency:

```toml
# govbrnews-mcp/pyproject.toml
[tool.poetry.dependencies]
data-platform = {path = "../data-platform", develop = true}
```

2. Update imports:

```python
# govbrnews-mcp/src/govbrnews_mcp/typesense_client.py
from data_platform.typesense import get_client, COLLECTION_SCHEMA
```

3. Test MCP functionality

4. Update documentation
```

#### 7.2 Update Main Documentation

**Update**: `README.md`

Add Typesense section:

```markdown
## Typesense Integration

Data-platform includes full Typesense support for search and indexing.

### Features

- Full and incremental data loading from HuggingFace
- Collection schema management
- Embedding synchronization
- Docker image for standalone deployment

### Quick Start

```bash
# Load data into Typesense
data-platform typesense-load --mode full

# Incremental update (last 7 days)
data-platform typesense-load --mode incremental --days 7

# Delete collection
data-platform typesense-delete --confirm
```

See [docs/typesense/](docs/typesense/) for details.
```

#### 7.3 Create Migration Guide

**Create**: `docs/typesense/MIGRATION_GUIDE.md`

```markdown
# Typesense Migration Guide

## For Users of Old Typesense Repo

The Typesense repository has been consolidated into data-platform as of 2025-12-27.

### Import Path Changes

| Old (typesense repo) | New (data-platform) |
|---------------------|-------------------|
| `from typesense_dgb import get_client` | `from data_platform.typesense import get_client` |
| `from typesense_dgb.collection import COLLECTION_SCHEMA` | `from data_platform.typesense import COLLECTION_SCHEMA` |
| `from typesense_dgb.indexer import index_documents` | `from data_platform.typesense import index_documents` |

### CLI Command Changes

| Old | New |
|-----|-----|
| `python scripts/load_data.py --mode full` | `data-platform typesense-load --mode full` |
| `python scripts/delete_collection.py --confirm` | `data-platform typesense-delete --confirm` |

### Docker Image Changes

| Old | New |
|-----|-----|
| `destaquesgovbr/typesense:latest` | `gcr.io/.../data-platform/typesense:latest` |

### MCP Server Updates

See [mcp-integration.md](mcp-integration.md) for MCP server migration steps.

### Timeline

- **2025-12-27**: Migration completed
- **2025-01-15**: Deprecation period begins (warnings in old repo)
- **2025-02-15**: Old repo archived (read-only)

### Support

For issues, open tickets in data-platform repo:
https://github.com/destaquesgovbr/data-platform/issues
```

#### 7.4 Archive Old Repository

**In typesense repo**:

**Update**: `README.md`

```markdown
# ⚠️ ARCHIVED: This Repository Has Moved

As of 2025-12-27, this repository has been **consolidated into data-platform**.

## New Location

**👉 https://github.com/destaquesgovbr/data-platform**

All Typesense functionality is now in:
- `src/data_platform/typesense/` - Core library
- `src/data_platform/jobs/typesense/` - Jobs
- `docker/typesense/` - Docker image

## Migration Guide

See: https://github.com/destaquesgovbr/data-platform/blob/main/docs/typesense/MIGRATION_GUIDE.md

## Why Consolidated?

- Single source of truth for all data operations
- Unified CI/CD and workflows
- Better integration with PostgreSQL and embeddings
- Simplified dependency management

---

**This repository is now read-only and will not receive updates.**

**Last active version**: v1.0.0 (2025-12-27)
```

**Archive Steps**:

1. Create final release: `v1.0.0-final`
2. Tag with migration notes
3. Update repo settings to read-only
4. Add archived banner to GitHub
5. Update all references in other repos

#### Checklist

- [ ] Migrate documentation to docs/typesense/
- [ ] Create architecture.md
- [ ] Create mcp-integration.md
- [ ] Create MIGRATION_GUIDE.md
- [ ] Update main README
- [ ] Archive typesense repo
- [ ] Update references in related repos

---

## 6. Workflow Consolidation

### Current State

**Typesense Repo Workflows**:

1. **docker-build-push.yml**
   - Trigger: Push to main, manual
   - Builds Docker image
   - Pushes to Artifact Registry

2. **typesense-daily-load.yml**
   - Trigger: Cron (daily 10:00 UTC)
   - Incremental load (last 7 days)
   - Triggers portal cache refresh

3. **typesense-full-reload.yml**
   - Trigger: Manual only
   - Deletes collection
   - Full reload from HuggingFace
   - Requires DELETE confirmation

4. **test-local.yml**
   - Trigger: Push, PR
   - Runs basic tests
   - ⚠️ Minimal coverage

**Data-Platform Workflows**:

1. **main-workflow.yaml**
   - Trigger: Cron (daily), manual
   - Runs full pipeline (scrape → enrich → sync)

2. **pipeline-steps.yaml**
   - Reusable workflow
   - Individual job definitions

3. **docker-build.yaml**
   - Builds main data-platform image

### Target State

**Consolidated Workflows**:

```
.github/workflows/
├── main-workflow.yaml              # Daily pipeline + Typesense incremental
├── pipeline-steps.yaml             # All pipeline jobs (including Typesense)
├── docker-build.yaml               # Builds BOTH images (main + typesense)
├── typesense-full-reload.yaml      # Manual full reload (separate)
└── test.yaml                       # All tests (unit + integration)
```

### Consolidation Matrix

| Workflow | Source | Merge Target | Strategy |
|----------|--------|--------------|----------|
| **docker-build-push** | typesense | `docker-build.yaml` | Add job for typesense image |
| **typesense-daily-load** | typesense | `main-workflow.yaml` | Add as final step after embeddings |
| **typesense-full-reload** | typesense | New file (standalone) | Keep separate, update image |
| **test-local** | typesense | `test.yaml` | Merge into comprehensive test workflow |

### Workflow Dependencies

```
Daily Pipeline Flow:

scrape-govbr
    ↓
scrape-ebc
    ↓
upload-cogfy
    ↓
[wait 20 min]
    ↓
enrich-themes
    ↓
generate-embeddings
    ↓
sync-embeddings-to-typesense
    ↓
typesense-incremental-load  ← NEW: Final step
```

### Implementation

**See Phase 5 for detailed workflow code.**

---

## 7. Testing Strategy

### Testing Levels

#### Level 1: Unit Tests (No External Dependencies)

**Coverage**: 80%+ for new code

**Test Files**:
- `tests/unit/typesense/test_client.py` - Client creation, configuration
- `tests/unit/typesense/test_collection.py` - Schema validation, collection ops
- `tests/unit/typesense/test_indexer.py` - Document preparation, tag cleaning
- `tests/unit/typesense/test_dataset_loader.py` - HuggingFace mocking

**Execution**:
```bash
poetry run pytest tests/unit/typesense/ -v --cov=data_platform.typesense
```

**Success Criteria**:
- All unit tests pass
- Coverage > 80%
- No flaky tests
- < 10s execution time

#### Level 2: Integration Tests (Requires Typesense)

**Test Files**:
- `tests/integration/test_typesense_loader.py` - Full/incremental load
- `tests/integration/test_collection_management.py` - Create/delete operations
- `tests/integration/test_search.py` - Query functionality

**Setup**:
```bash
# Local Docker
docker run -d --name typesense-test \
  -p 8108:8108 \
  typesense/typesense:27.1 \
  --data-dir=/data --api-key=test-key

# Run tests
export TYPESENSE_HOST=localhost
export TYPESENSE_PORT=8108
export TYPESENSE_API_KEY=test-key
poetry run pytest tests/integration/test_typesense*.py -v -m integration
```

**Success Criteria**:
- All integration tests pass
- Test with small dataset (< 100 records)
- Cleanup after tests
- < 60s execution time

#### Level 3: End-to-End Tests (Full Workflow)

**Manual Test Plan**:

1. **Full Load Test**
   ```bash
   # Delete collection
   data-platform typesense-delete --confirm

   # Full load with limit
   data-platform typesense-load --mode full --limit 1000

   # Verify
   data-platform typesense-list
   ```

   **Expected**: 1000 documents indexed

2. **Incremental Load Test**
   ```bash
   # Incremental load
   data-platform typesense-load --mode incremental --days 7

   # Verify new documents added
   data-platform typesense-list
   ```

   **Expected**: Additional documents indexed

3. **Search Test**
   ```bash
   # Use MCP server or direct client
   curl -H "X-TYPESENSE-API-KEY: ..." \
     "http://localhost:8108/collections/news/documents/search?q=educação&query_by=title"
   ```

   **Expected**: Relevant results returned

4. **Docker Test**
   ```bash
   # Build image
   docker build -f docker/typesense/Dockerfile -t typesense-test .

   # Run
   docker run --rm -e TYPESENSE_API_KEY=test-key typesense-test
   ```

   **Expected**: Container starts, loads data, serves requests

5. **Workflow Test** (GitHub Actions)
   - Trigger manual workflow
   - Monitor logs
   - Verify completion

   **Expected**: All jobs succeed

**Success Criteria**:
- All manual tests pass
- No errors in logs
- Performance acceptable (< 5 min for 1000 docs)
- MCP server works after migration

### Test Data

**Use Existing Test Data**:
- HuggingFace test split (if available)
- Synthetic test records (10-100)
- Limit parameter for production data

**Do NOT**:
- Load full 300k dataset in tests
- Use production Typesense in tests
- Commit test data to repo (use fixtures)

### Regression Testing

**Critical Paths to Test**:

1. **MCP Server** - Ensure no breaking changes
   ```bash
   # In govbrnews-mcp repo
   poetry run pytest -v
   ```

2. **Existing Typesense Sync** (embeddings)
   ```bash
   # Ensure typesense_sync.py still works
   poetry run pytest tests/unit/test_typesense_sync.py -v
   ```

3. **Portal Integration** - Manual smoke test
   - Visit portal
   - Perform search
   - Verify results

### Automated Testing in CI

**GitHub Actions Workflow** (`.github/workflows/test.yaml`):

```yaml
name: Test Suite

on:
  push:
    branches: [main, migrate/**]
  pull_request:

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install poetry && poetry install
      - run: poetry run pytest tests/unit/ -v --cov=data_platform

  integration-tests-typesense:
    runs-on: ubuntu-latest
    services:
      typesense:
        image: typesense/typesense:27.1
        env:
          TYPESENSE_API_KEY: test-key
        ports:
          - 8108:8108
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install poetry && poetry install
      - run: |
          poetry run pytest tests/integration/test_typesense*.py -v -m integration
        env:
          TYPESENSE_HOST: localhost
          TYPESENSE_PORT: 8108
          TYPESENSE_API_KEY: test-key
```

**Success Criteria for CI**:
- All tests pass
- Coverage > 75% overall
- No flaky tests
- < 5 min total execution

---

## 8. Deployment Plan

### Pre-Deployment Checklist

- [ ] All code migrated and tested
- [ ] Unit tests pass (100%)
- [ ] Integration tests pass (100%)
- [ ] Documentation complete
- [ ] Docker images build successfully
- [ ] Workflows validated
- [ ] MCP server compatibility verified
- [ ] Team review completed

### Deployment Phases

#### Phase 1: Soft Launch (Week 4, Day 1-2)

**Objective**: Deploy to staging/test environment

**Steps**:

1. **Merge to main branch**
   ```bash
   git checkout main
   git merge migrate/typesense-consolidation
   git push origin main
   ```

2. **Trigger Docker build**
   - Automatic on push to main
   - Monitor GitHub Actions
   - Verify images in Artifact Registry

3. **Test in staging**
   ```bash
   # Deploy to test Typesense instance
   docker pull gcr.io/.../data-platform/typesense:latest

   # Run test load
   docker run --rm \
     -e TYPESENSE_HOST=test-typesense \
     -e TYPESENSE_API_KEY=$TEST_API_KEY \
     -e HF_TOKEN=$HF_TOKEN \
     gcr.io/.../data-platform/typesense:latest \
     data-platform typesense-load --mode full --limit 10000
   ```

4. **Validate**
   - Check logs for errors
   - Query test collection
   - Verify MCP access

**Rollback**: If issues found, pause and fix before production

#### Phase 2: Production Deployment (Week 4, Day 3-4)

**Objective**: Deploy to production Typesense

**Steps**:

1. **Announce maintenance window**
   - Duration: 2 hours
   - Impact: Typesense read-only during reload

2. **Backup production data**
   ```bash
   # Export current Typesense data
   # (via Typesense export API or snapshot)
   ```

3. **Deploy new Docker image**
   ```bash
   # Update Compute Engine instance or Cloud Run
   # with new image URL
   ```

4. **Run full reload** (manual workflow trigger)
   - Go to GitHub Actions
   - Run typesense-full-reload.yaml
   - Type "DELETE" to confirm
   - Monitor execution

5. **Verify production**
   - Check collection stats
   - Perform test searches
   - Verify MCP server works
   - Check portal search

6. **Enable daily workflow**
   - Ensure cron trigger is active
   - Monitor first automated run

**Success Criteria**:
- Full reload completes (< 30 min)
- All documents indexed
- No errors in logs
- MCP server functional
- Portal search works

**Rollback Plan**: See Section 9

#### Phase 3: Monitor & Optimize (Week 4, Day 5-7)

**Objective**: Monitor for issues and optimize

**Monitoring**:

1. **Daily Checks**
   - Check workflow execution logs
   - Monitor Typesense metrics
   - Check MCP server usage

2. **Performance Metrics**
   - Load time (target: < 30 min full, < 5 min incremental)
   - Query latency (target: < 100ms)
   - Memory usage
   - Disk usage

3. **Error Tracking**
   - GitHub Actions failures
   - Typesense errors
   - MCP server errors

**Optimization**:
- Adjust batch sizes if needed
- Tune Typesense settings
- Optimize queries

#### Phase 4: Archive Old Repo (Week 5)

**Objective**: Officially deprecate typesense repo

**Steps**:

1. **Update old repo README**
   - Add archived banner
   - Link to data-platform
   - Include migration guide

2. **Set repo to read-only**
   - GitHub settings → Archive

3. **Update references**
   - In docs
   - In related repos (govbrnews-mcp, portal)
   - In wikis/documentation sites

4. **Announce completion**
   - Email to team
   - Update project documentation
   - Close related issues

### Deployment Timeline

| Day | Phase | Activities | Duration |
|-----|-------|-----------|----------|
| Mon | Soft Launch | Merge, build, test | 4h |
| Tue | Soft Launch | Staging validation | 2h |
| Wed | Production | Backup, deploy, reload | 3h |
| Thu | Production | Verify, monitor | 2h |
| Fri | Monitor | Daily checks, optimization | 1h |
| Mon+7 | Monitor | Continue monitoring | 1h/day |
| Mon+14 | Archive | Archive old repo | 2h |

**Total Effort**: ~20 hours over 3 weeks

---

## 9. Rollback Plan

### Rollback Scenarios

#### Scenario 1: Issues Found During Soft Launch (Phase 1)

**Impact**: Low (no production impact)

**Actions**:
1. Do not proceed to production deployment
2. Fix issues in migration branch
3. Re-test
4. Attempt deployment again

**Rollback**: N/A (never reached production)

#### Scenario 2: Issues During Production Deployment (Phase 2)

**Impact**: Medium (Typesense temporarily unavailable)

**Symptoms**:
- Full reload fails
- Collection not created
- Docker image fails to start

**Actions**:
1. **Immediate**: Stop deployment
2. **Restore**: Use old Typesense image
   ```bash
   # Revert to previous image
   docker pull gcr.io/.../typesense:v1.0.0
   docker run ...
   ```
3. **Restore data**: From backup if needed
4. **Investigate**: Check logs, identify issue
5. **Fix**: Address in migration branch
6. **Retry**: After fix validated

**Recovery Time**: < 30 minutes

#### Scenario 3: Issues After Production Deployment (Phase 3)

**Impact**: Medium-High (production using new system)

**Symptoms**:
- Daily workflow fails
- MCP server breaks
- Portal search broken
- Performance degradation

**Actions**:

**Step 1: Assess Severity**

| Severity | Symptoms | Action |
|----------|----------|--------|
| **Critical** | Portal down, no search | Immediate rollback |
| **High** | Workflow fails, partial data | Rollback within 24h |
| **Medium** | MCP issues, slow queries | Fix forward, rollback if needed |
| **Low** | Minor bugs, edge cases | Fix forward |

**Step 2: Rollback (if needed)**

1. **Pause daily workflow**
   ```yaml
   # Comment out typesense-incremental job in main-workflow.yaml
   ```

2. **Revert Docker image**
   ```bash
   # Use old typesense repo image
   docker pull gcr.io/.../typesense:legacy-final
   ```

3. **Restore collection**
   - Option A: Keep current data (if intact)
   - Option B: Reload from HuggingFace using old image

4. **Revert MCP server** (if affected)
   ```bash
   cd /path/to/govbrnews-mcp
   git revert <commit>  # Revert to old imports
   ```

5. **Monitor recovery**
   - Check portal
   - Test MCP
   - Verify searches

**Step 3: Post-Incident**

1. Document root cause
2. Fix in migration branch
3. Test thoroughly
4. Plan retry

**Recovery Time**: 1-2 hours

#### Scenario 4: Gradual Degradation (Phase 3+)

**Impact**: Medium (performance/quality issues)

**Symptoms**:
- Slower queries over time
- Memory leaks
- Stale data

**Actions**:
1. **Monitor**: Identify specific issue
2. **Mitigate**: Adjust settings, restart services
3. **Fix forward**: Address in new PR
4. **Rollback**: Only if unfixable

### Rollback Checklist

**Before Rollback**:
- [ ] Identify root cause
- [ ] Determine severity
- [ ] Notify team
- [ ] Document decision

**During Rollback**:
- [ ] Pause affected workflows
- [ ] Deploy previous version
- [ ] Restore data if needed
- [ ] Verify functionality
- [ ] Monitor for issues

**After Rollback**:
- [ ] Post-mortem meeting
- [ ] Document lessons learned
- [ ] Update migration plan
- [ ] Plan retry timeline

### Emergency Contacts

| Role | Contact | Responsibility |
|------|---------|----------------|
| Tech Lead | [Name] | Final rollback decision |
| DevOps | [Name] | Infrastructure operations |
| Developer | [Name] | Code fixes |

### Rollback Decision Matrix

| Time Since Deploy | Severity | Decision |
|------------------|----------|----------|
| < 24h | Critical | Immediate rollback |
| < 24h | High | Assess, likely rollback |
| < 24h | Medium | Fix forward |
| 24h-1wk | Critical | Rollback + fix |
| 24h-1wk | High | Fix forward preferred |
| 24h-1wk | Medium | Fix forward |
| > 1wk | Any | Fix forward only |

**Rationale**: After 1 week, too much new data; rolling back creates data inconsistency.

---

## 10. Risk Assessment

### Risk Matrix

| Risk | Probability | Impact | Severity | Mitigation |
|------|------------|--------|----------|------------|
| **Breaking MCP Server** | Medium | High | **HIGH** | Extensive testing, compatibility layer |
| **Workflow Failures** | Medium | Medium | **MEDIUM** | Gradual rollout, monitoring |
| **Import Path Conflicts** | Low | High | **MEDIUM** | Namespace separation, deprecation warnings |
| **Data Loss** | Low | Critical | **MEDIUM** | Backups, idempotent operations |
| **Performance Degradation** | Low | Medium | **LOW** | Load testing, monitoring |
| **Documentation Gaps** | High | Low | **LOW** | Comprehensive docs, migration guide |

### Detailed Risk Analysis

#### Risk 1: Breaking MCP Server

**Description**: MCP server depends on Typesense client code. Import changes could break it.

**Probability**: Medium (40%)
- MCP has direct Typesense dependency
- Import paths will change
- Not all edge cases tested

**Impact**: High
- MCP server unusable
- Claude Desktop integration broken
- User-facing feature down

**Mitigation Strategies**:

1. **Pre-Migration**:
   - Add data-platform as MCP dependency
   - Create compatibility shim
   - Test MCP with new imports

2. **During Migration**:
   - Test MCP after each phase
   - Keep MCP repo CI passing
   - Coordinate MCP updates

3. **Post-Migration**:
   - Immediate MCP verification
   - Rollback plan ready

**Contingency**:
- Maintain old typesense package as fallback
- MCP can pin to old version temporarily

#### Risk 2: Workflow Failures

**Description**: GitHub Actions workflows may fail due to missing dependencies, wrong paths, etc.

**Probability**: Medium (50%)
- Complex workflow dependencies
- Multi-repo coordination
- Secret/env variable changes

**Impact**: Medium
- Daily pipeline broken
- Manual intervention needed
- Data freshness issues

**Mitigation**:

1. **Test workflows in fork**
2. **Gradual rollout** (manual triggers first)
3. **Monitor closely** during first week
4. **Have rollback workflow** ready

**Contingency**:
- Run jobs manually if needed
- Use old workflow temporarily

#### Risk 3: Import Path Conflicts

**Description**: Users/systems importing old paths break.

**Probability**: Low (20%)
- Controlled environment
- Limited external users
- Deprecation warnings

**Impact**: High
- Other repos break
- User scripts fail

**Mitigation**:

1. **Compatibility package** (temporary)
   ```python
   # typesense_dgb (shim package)
   from data_platform.typesense import *
   ```

2. **Deprecation warnings**
3. **Clear migration guide**
4. **Gradual deprecation** (3 month window)

**Contingency**:
- Publish shim package to PyPI
- Extend deprecation period

#### Risk 4: Data Loss

**Description**: Migration error causes data loss in Typesense.

**Probability**: Low (10%)
- Idempotent operations
- Upsert mode default
- No delete operations without confirmation

**Impact**: Critical
- Search broken
- Portal unusable
- User trust lost

**Mitigation**:

1. **Backups before deployment**
2. **Idempotent operations** (upsert only)
3. **Test with limited dataset**
4. **Manual verification** before production

**Contingency**:
- Restore from backup
- Reload from HuggingFace (takes ~30 min)

#### Risk 5: Performance Degradation

**Description**: New code is slower, uses more memory, etc.

**Probability**: Low (15%)
- Similar code, just moved
- No major algorithmic changes

**Impact**: Medium
- Slower loads
- Higher costs
- Possible timeouts

**Mitigation**:

1. **Benchmark before/after**
2. **Load testing** with production data
3. **Monitor metrics** post-deploy
4. **Profiling** if issues found

**Contingency**:
- Optimize code
- Rollback if severe

#### Risk 6: Documentation Gaps

**Description**: Users confused, can't find info on new structure.

**Probability**: High (70%)
- Large documentation surface
- Migration creates disruption
- Multiple audiences (devs, users, MCP)

**Impact**: Low
- Confusion
- Support requests
- Slower adoption

**Mitigation**:

1. **Comprehensive docs** (this plan)
2. **Migration guide** with examples
3. **FAQ** for common issues
4. **Team training** session

**Contingency**:
- Create missing docs on-demand
- Video tutorials if needed

### Risk Monitoring

**During Migration**:
- [ ] Daily standup on progress
- [ ] Track blockers in GitHub issues
- [ ] Monitor CI/CD pipelines

**Post-Deployment**:
- [ ] Daily checks for 1 week
- [ ] Weekly checks for 1 month
- [ ] Monthly checks for 3 months

**Escalation**:
- Critical issues → Immediate team meeting
- High issues → Same-day discussion
- Medium/Low → Track in backlog

---

## 11. Success Criteria

### Technical Success Criteria

#### Code Quality

- [ ] All unit tests pass (100%)
- [ ] Integration tests pass (100%)
- [ ] Code coverage > 80% for new code
- [ ] No linting errors (ruff, mypy)
- [ ] All imports resolved correctly

#### Functionality

- [ ] Full load works (HuggingFace → Typesense)
- [ ] Incremental load works (daily updates)
- [ ] Collection management works (create, delete, list)
- [ ] MCP server still functional
- [ ] Portal search works
- [ ] Embeddings sync works

#### Performance

- [ ] Full load < 30 minutes (300k docs)
- [ ] Incremental load < 5 minutes
- [ ] Query latency < 100ms (p95)
- [ ] Memory usage stable (no leaks)
- [ ] Docker image size < 2GB

#### Infrastructure

- [ ] Docker images build successfully
- [ ] GitHub Actions workflows pass
- [ ] Secrets configured correctly
- [ ] Monitoring in place
- [ ] Alerting configured

### Documentation Success Criteria

- [ ] Migration guide published
- [ ] Architecture docs updated
- [ ] MCP integration docs created
- [ ] README updated
- [ ] API docs generated
- [ ] Changelog created

### Process Success Criteria

- [ ] All phases completed on schedule
- [ ] No production incidents
- [ ] Team trained on new structure
- [ ] Old repo archived
- [ ] Post-migration review completed

### User Success Criteria

- [ ] MCP users can still use Claude integration
- [ ] Portal users see no disruption
- [ ] Developers can find documentation
- [ ] No support requests due to migration

### Business Success Criteria

- [ ] Zero downtime during migration
- [ ] No data loss
- [ ] No cost increase
- [ ] Improved maintainability
- [ ] Faster feature development (post-migration)

### Validation Checklist

**Week 1 (Post-Deployment)**:
- [ ] All automated tests passing
- [ ] Manual smoke tests pass
- [ ] No critical bugs reported
- [ ] Monitoring shows healthy metrics

**Week 2**:
- [ ] Daily workflow runs successfully
- [ ] MCP server usage stable
- [ ] Performance within targets
- [ ] No rollbacks needed

**Week 4**:
- [ ] Old repo archived
- [ ] All references updated
- [ ] Team proficient with new structure
- [ ] Documentation feedback incorporated

**Month 3**:
- [ ] No migration-related issues
- [ ] New features shipped using new structure
- [ ] Developer satisfaction improved

### Metrics to Track

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| **Test Pass Rate** | N/A | 100% | GitHub Actions |
| **Code Coverage** | ~60% (old) | >80% (new) | pytest-cov |
| **Load Time (Full)** | ~25 min | <30 min | Workflow logs |
| **Load Time (Incremental)** | ~3 min | <5 min | Workflow logs |
| **Query Latency (p95)** | ~80ms | <100ms | Typesense metrics |
| **Workflow Success Rate** | ~95% | >98% | GitHub Actions |
| **MCP Uptime** | ~99% | >99% | Monitoring |
| **Documentation Coverage** | ~70% | >90% | Manual review |

### Sign-Off

**Required Approvals**:

- [ ] Tech Lead (code review)
- [ ] DevOps (infrastructure review)
- [ ] Product (user impact review)
- [ ] QA (testing sign-off)

**Final Approval**: Tech Lead

**Date**: ___________

---

## Appendix A: File Mapping Table

| Source (typesense) | Destination (data-platform) | Action | Priority |
|--------------------|----------------------------|--------|----------|
| `src/typesense_dgb/__init__.py` | `src/data_platform/typesense/__init__.py` | Migrate | HIGH |
| `src/typesense_dgb/client.py` | `src/data_platform/typesense/client.py` | Migrate | HIGH |
| `src/typesense_dgb/collection.py` | `src/data_platform/typesense/collection.py` | Migrate | HIGH |
| `src/typesense_dgb/dataset.py` | `src/data_platform/typesense/dataset_loader.py` | Migrate + Rename | HIGH |
| `src/typesense_dgb/indexer.py` | `src/data_platform/typesense/indexer.py` | Migrate | HIGH |
| `src/typesense_dgb/utils.py` | `src/data_platform/typesense/utils.py` | Migrate | MEDIUM |
| `scripts/load_data.py` | `src/data_platform/jobs/typesense/full_load.py` | Refactor | HIGH |
| `scripts/delete_collection.py` | `src/data_platform/jobs/typesense/collection_manager.py` | Refactor | MEDIUM |
| `scripts/create_search_key.py` | `src/data_platform/jobs/typesense/collection_manager.py` | Merge | LOW |
| `Dockerfile` | `docker/typesense/Dockerfile` | Migrate + Update | HIGH |
| `entrypoint.sh` | `docker/typesense/entrypoint.sh` | Migrate + Update | HIGH |
| `run-typesense-server.sh` | `scripts/run-typesense-server.sh` | Migrate | MEDIUM |
| `test_init_typesense.py` | `tests/integration/test_typesense_loader.py` | Refactor | MEDIUM |
| `README.md` | `docs/typesense/README.md` | Migrate + Update | HIGH |
| `docs/setup.md` | `docs/typesense/setup.md` | Migrate | MEDIUM |
| `docs/data-management.md` | `docs/typesense/data-management.md` | Migrate | MEDIUM |
| `docs/development.md` | `docs/typesense/development.md` | Migrate | MEDIUM |
| `.github/workflows/docker-build-push.yml` | `.github/workflows/docker-build.yaml` | Merge | HIGH |
| `.github/workflows/typesense-daily-load.yml` | `.github/workflows/main-workflow.yaml` | Merge | HIGH |
| `.github/workflows/typesense-full-reload.yml` | `.github/workflows/typesense-full-reload.yaml` | Migrate | MEDIUM |
| `.github/workflows/test-local.yml` | `.github/workflows/test.yaml` | Merge | LOW |
| `pyproject.toml` | `pyproject.toml` | Merge dependencies | HIGH |
| `web-ui/` | Archive (separate) | Archive | LOW |
| Various docs | `docs/typesense/` | Consolidate | MEDIUM |

**Legend**:
- **Migrate**: Copy file with minimal changes
- **Refactor**: Rewrite to fit new structure
- **Merge**: Combine with existing file
- **Archive**: Keep for reference, don't migrate

---

## Appendix B: Dependency Analysis

### Typesense Repo Dependencies (pyproject.toml)

```toml
[project.dependencies]
datasets = ">=3.1.0"           # ✅ Already in data-platform
pandas = ">=2.2.3"             # ✅ Already in data-platform
typesense = ">=0.21.0"         # ➕ ADD to data-platform
huggingface_hub = ">=0.25.2"   # ✅ Already in data-platform
requests = ">=2.32.3"          # ✅ Already in data-platform
python-dotenv = ">=1.0.1"      # ✅ Already in data-platform

[project.optional-dependencies.dev]
pytest = ">=7.0.0"             # ✅ Already in data-platform
pytest-cov = ">=4.0.0"         # ✅ Already in data-platform
black = ">=23.0.0"             # ✅ Already in data-platform
ruff = ">=0.1.0"               # ✅ Already in data-platform
mypy = ">=1.0.0"               # ✅ Already in data-platform
```

**Result**: Only need to add `typesense>=0.21.0` to data-platform.

### Dependency Conflicts

**Check for Version Conflicts**:

| Package | Typesense Repo | Data-Platform | Conflict? |
|---------|----------------|---------------|-----------|
| `datasets` | >=3.1.0 | >=3.1.0 | ❌ No |
| `pandas` | >=2.2.3 | >=2.1.4 | ⚠️ Minor (use >=2.2.3) |
| `requests` | >=2.32.3 | ^2.32.3 | ❌ No |
| `python-dotenv` | >=1.0.1 | ^1.0.0 | ❌ No |

**Resolution**: Bump pandas to >=2.2.3 in data-platform.

### External Dependencies

**Runtime**:
- Typesense server (self-hosted or cloud)
- HuggingFace Hub API
- Google Cloud (Artifact Registry, Secret Manager)

**Development**:
- Docker
- pytest
- GitHub Actions

**No Breaking Changes Expected**

---

## Appendix C: Timeline & Milestones

### Gantt Chart (Text Format)

```
Week 1: Preparation & Core Migration
├─ Mon-Tue: Phase 1 (Preparation)
│  └─ Create branches, structure, dependencies
├─ Wed-Thu: Phase 2 (Core Library)
│  └─ Migrate modules, update imports
└─ Fri: Phase 2 continued
   └─ Create TypesenseManager, test

Week 2: Jobs & Docker
├─ Mon-Tue: Phase 3 (Jobs Migration)
│  └─ Migrate scripts, update CLI
├─ Wed-Thu: Phase 4 (Docker)
│  └─ Migrate Dockerfile, entrypoint, test
└─ Fri: Testing
   └─ Unit tests, integration tests

Week 3: Workflows & Testing
├─ Mon-Tue: Phase 5 (Workflows)
│  └─ Merge workflows, test GitHub Actions
├─ Wed-Thu: Phase 6 (Testing)
│  └─ E2E tests, MCP validation
└─ Fri: Documentation
   └─ Write docs, migration guide

Week 4: Deployment & Cleanup
├─ Mon: Phase 7 (Soft Launch)
│  └─ Merge to main, test staging
├─ Tue-Wed: Production Deployment
│  └─ Backup, deploy, full reload
├─ Thu-Fri: Monitor
│  └─ Daily checks, optimization
└─ Week 5: Archive old repo
```

### Key Milestones

| Milestone | Date | Deliverable | Owner |
|-----------|------|------------|-------|
| **M1: Preparation Complete** | Week 1, Fri | Structure created, dependencies added | Dev |
| **M2: Core Migration Complete** | Week 2, Tue | All code migrated, tests pass | Dev |
| **M3: Docker Ready** | Week 2, Fri | Docker builds, loads data | DevOps |
| **M4: Workflows Merged** | Week 3, Wed | All workflows working in CI | Dev |
| **M5: Testing Complete** | Week 3, Fri | All tests pass, MCP validated | QA |
| **M6: Docs Complete** | Week 3, Fri | All documentation published | Tech Writer |
| **M7: Staging Deployed** | Week 4, Mon | Staging environment validated | DevOps |
| **M8: Production Deployed** | Week 4, Wed | Production using new system | DevOps |
| **M9: Monitoring Stable** | Week 4, Fri | 1 week of stable operation | All |
| **M10: Old Repo Archived** | Week 5 | Typesense repo read-only | Admin |

### Critical Path

```
Preparation → Core Migration → Jobs → Docker → Workflows → Testing → Deployment
```

**Bottlenecks**:
- Testing (requires all previous phases)
- Production deployment (requires testing sign-off)

**Buffer**: 20% (5 days extra for unexpected issues)

---

## Appendix D: Contact & Resources

### Team

| Role | Name | Contact | Responsibility |
|------|------|---------|----------------|
| **Tech Lead** | [Name] | [Email] | Overall migration, code review |
| **DevOps Engineer** | [Name] | [Email] | Infrastructure, Docker, CI/CD |
| **Backend Developer** | [Name] | [Email] | Code migration, testing |
| **QA Engineer** | [Name] | [Email] | Testing, validation |
| **Technical Writer** | [Name] | [Email] | Documentation |

### Resources

**Documentation**:
- This plan: `/data-platform/_plan/TYPESENSE_MIGRATION.md`
- Data-platform plan: `/data-platform/_plan/README.md`
- Typesense docs: https://typesense.org/docs/
- MCP docs: https://modelcontextprotocol.io/

**Repositories**:
- Data-platform: https://github.com/destaquesgovbr/data-platform
- Typesense (old): https://github.com/destaquesgovbr/typesense
- MCP Server: https://github.com/destaquesgovbr/govbrnews-mcp

**Infrastructure**:
- Typesense server: `typesense-server.southamerica-east1-a.c.inspire-7-finep.internal:8108`
- Artifact Registry: `southamerica-east1-docker.pkg.dev/inspire-7-finep/data-platform`
- Secret Manager: `typesense-api-key`, `typesense-write-conn`

**Monitoring**:
- GitHub Actions: https://github.com/destaquesgovbr/data-platform/actions
- GCP Console: https://console.cloud.google.com/

### Support Channels

**During Migration**:
- Slack: #data-platform-migration
- Daily standups: 10:00 AM BRT
- Emergency: Page on-call

**Post-Migration**:
- Issues: GitHub Issues
- Questions: Slack #data-platform
- Documentation: Wiki

---

## Appendix E: Changelog

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2025-12-27 | 1.0 | Claude/Nitai | Initial comprehensive plan |

---

**End of Migration Plan**

**Total Pages**: ~40 (markdown)
**Total Words**: ~15,000
**Estimated Reading Time**: 60 minutes

**Next Steps**:
1. Review this plan with team
2. Approve and schedule
3. Create GitHub project board
4. Begin Phase 1

**Questions?** Contact tech lead or open a discussion in GitHub.
