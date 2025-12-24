# Architecture Overview

High-level architecture of the DestaquesGovBr Data Platform.

---

## System Context

The Data Platform manages the ingestion, storage, and distribution of Brazilian government news data.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DestaquesGovBr Ecosystem                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  RSS Feeds          Data Platform          Consumers            │
│  (~158 agencies)    (this repo)           (various)             │
│                                                                 │
│  ┌──────────┐      ┌──────────────┐      ┌──────────────┐      │
│  │ Gov RSS  │─────>│   Scraper    │      │  Typesense   │      │
│  │  Feeds   │      │              │      │   (Search)   │      │
│  └──────────┘      │   ┌──────┐   │      └──────────────┘      │
│                    │   │ DB   │<──────────────┐                │
│  ┌──────────┐      │   └──────┘   │      ┌────┴─────────┐      │
│  │  Cogfy   │─────>│  Enrichment  │      │ HuggingFace  │      │
│  │  (LLM)   │      │              │      │   Dataset    │      │
│  └──────────┘      │   ┌──────┐   │      └──────────────┘      │
│                    │   │Sync  │───┘                            │
│                    │   └──────┘   │      ┌──────────────┐      │
│                    └──────────────┘      │   Website    │      │
│                                          │   (Next.js)  │      │
│                                          └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Migration Strategy

The platform is migrating from HuggingFace Dataset to PostgreSQL as the primary data store.

### Phase Overview

```
Phase 0: Setup              ✅ Complete
  └─ Repository structure

Phase 1: Infrastructure     ✅ Complete
  └─ Cloud SQL PostgreSQL

Phase 2: PostgresManager    🚧 In Progress
  └─ Database access layer

Phase 3: Data Migration     ⏳ Planned
  └─ Migrate ~300k records

Phase 4: Dual-Write         ⏳ Planned
  └─ Write to both stores

Phase 5: PostgreSQL Primary ⏳ Planned
  └─ Switch to PostgreSQL

Phase 6: Consumer Migration ⏳ Planned
  └─ Update all consumers
```

See [Migration Plan](../../_plan/README.md) for details.

---

## Components

### 1. Data Storage

**PostgreSQL (Cloud SQL)**
- Primary data store (target)
- ~300k news records
- Partially normalized schema
- Full-text search support

**HuggingFace Dataset**
- Legacy primary store (current)
- Open data distribution (future)
- Daily sync from PostgreSQL

**Infrastructure**:
- Managed via Terraform
- VPC peering for private access
- Automated backups (30 days retention)
- Point-in-time recovery enabled

### 2. Data Pipeline

**Scraper Job**
- Fetches RSS feeds from ~158 government agencies
- Extracts news metadata
- Identifies duplicates via `unique_id` (MD5)
- Stores raw news data

**Enrichment Job**
- Sends news to Cogfy LLM for summarization
- Classifies into theme taxonomy (3-level hierarchy)
- Enriches with structured metadata

**HuggingFace Sync Job**
- Exports PostgreSQL data to HuggingFace Dataset
- Runs daily
- Tracks sync status via `synced_to_hf_at` field

### 3. Storage Adapters

**StorageAdapter Interface**
- Abstraction over storage backends
- Supports: HuggingFace, PostgreSQL, Dual-Write
- Allows gradual migration without code changes

```python
class StorageBackend(Enum):
    HUGGINGFACE = "huggingface"  # Legacy
    POSTGRES = "postgres"         # Target
    DUAL_WRITE = "dual_write"     # Transition
```

### 4. Managers

**PostgresManager**
- CRUD operations for PostgreSQL
- Connection pooling
- In-memory cache for agencies/themes
- Transaction management

**DatasetManager** (Legacy)
- CRUD operations for HuggingFace Dataset
- Being gradually replaced by PostgresManager

---

## Data Flow

### Current State (Phase 1-2)

```
RSS Feeds
   │
   ├─> Scraper ─────> HuggingFace Dataset ──> Consumers
   │                      │
   └─> Enrichment ────────┘
```

### Target State (Phase 5-6)

```
RSS Feeds
   │
   ├─> Scraper ─────> PostgreSQL ─────> Consumers
   │                      │
   └─> Enrichment ────────┤
                          │
                          └─> Daily Sync ──> HuggingFace Dataset
                                             (Open Data)
```

---

## Database Schema

Partially normalized for performance:

**Master Tables**:
- `agencies`: Government agencies (~158 records)
- `themes`: 3-level theme taxonomy (~150-200 records)

**Main Table**:
- `news`: News articles (~300k records)
  - Foreign keys to agencies/themes
  - Denormalized fields: `agency_key`, `agency_name`
  - Full-text search: Portuguese language support

**Auxiliary**:
- `sync_log`: Tracks sync operations
- `schema_version`: Migration tracking

See [Database Schema](../database/schema.md) for details.

---

## Technology Stack

### Backend
- **Language**: Python 3.11+
- **Database**: PostgreSQL 15 (Cloud SQL)
- **ORM**: SQLAlchemy 2.0
- **Data**: Pandas, PyArrow

### Infrastructure
- **Cloud**: Google Cloud Platform
- **IaC**: Terraform
- **CI/CD**: GitHub Actions
- **Secrets**: GCP Secret Manager

### Development
- **Package Manager**: Poetry
- **Testing**: pytest
- **Linting**: Ruff, Black
- **Type Checking**: mypy

### Data Processing
- **HuggingFace**: datasets, huggingface-hub
- **LLM**: Cogfy (external service)
- **Search**: Typesense (external consumer)

---

## Design Principles

### 1. Gradual Migration

Migrate incrementally to minimize risk:
1. Setup infrastructure
2. Implement PostgresManager
3. Migrate data
4. Enable dual-write
5. Switch primary store
6. Update consumers

### 2. Backward Compatibility

During migration:
- Both storage backends remain functional
- Consumers can still use HuggingFace
- No breaking changes to external APIs

### 3. Performance

Optimize for common access patterns:
- Denormalize frequently-joined fields
- Index on date ranges (recent news)
- Cache master data (agencies, themes)
- Connection pooling

### 4. Data Integrity

Ensure data consistency:
- Unique constraint on `unique_id`
- Foreign key constraints
- Triggers for auto-updates
- Validation before insertion

### 5. Observability

Track operations:
- `sync_log` table for all sync operations
- Query insights enabled
- Slow query logging (>1 second)
- Database performance metrics

---

## Key Decisions

See [Architecture Decision Records](../../_plan/DECISIONS.md) for detailed rationale.

**ADR-001**: PostgreSQL as primary database
- Cloud SQL for managed service
- Superior query capabilities
- Better for structured data

**ADR-002**: Daily sync to HuggingFace
- Maintain open data distribution
- Reduce dependency on HF infrastructure
- Keep community access

**ADR-003**: Partially normalized schema
- Balance normalization vs performance
- Denormalize agency fields in news
- Normalized agencies and themes

**ADR-004**: Hybrid repository architecture
- Separate infra and data-platform repos
- Terraform in infra repo
- Application code in data-platform repo

**ADR-005**: Gradual migration with dual-write
- Minimize risk
- Allow rollback
- Test thoroughly before switching

---

## Security

### Authentication
- GCP service accounts
- Workload Identity Federation (GitHub Actions)
- Cloud SQL Proxy for secure connections

### Secrets Management
- All credentials in Secret Manager
- No secrets in code or config files
- Automatic rotation support

### Network Security
- Private IP for Cloud SQL
- VPC peering with Service Networking
- Authorized networks for external access

### Data Protection
- Deletion protection on Cloud SQL
- Automated backups (30 days)
- Point-in-time recovery (7 days)
- Encryption at rest and in transit

---

## Scalability

### Current Scale
- ~158 government agencies
- ~300k news articles
- ~150-200 themes
- Daily updates

### Growth Strategy

**Vertical Scaling**:
- Cloud SQL tier can be upgraded
- Current: db-custom-1-3840 (1 vCPU, 3.75GB)
- Can scale to: db-custom-96-360448 (96 vCPU, 360GB)

**Storage Scaling**:
- Auto-resize enabled (50GB → 500GB)
- Can increase limit as needed

**High Availability**:
- Currently: ZONAL (single zone)
- Can enable: REGIONAL (multi-zone replica)
- Automatic failover

**Connection Pooling**:
- PostgresManager uses connection pools
- Prevents connection exhaustion
- Configurable pool size

---

## Monitoring

### Database
- Cloud SQL Query Insights
- Slow query logging (>1 second)
- Connection metrics
- Disk usage alerts

### Application
- `sync_log` table tracks all operations
- Loguru for structured logging
- Error tracking via logs

### Infrastructure
- Cloud SQL backups status
- VPC peering health
- Secret Manager access logs

---

See also:
- [Database Schema](../database/schema.md)
- [Development Setup](../development/setup.md)
- [Migration Plan](../../_plan/README.md)
