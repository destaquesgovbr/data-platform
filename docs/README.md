# Documentation

Comprehensive documentation for the DestaquesGovBr Data Platform.

---

## Quick Links

| Category | Document | Description |
|----------|----------|-------------|
| **Getting Started** | [Development Setup](development/setup.md) | Set up your development environment |
| **Architecture** | [Overview](architecture/overview.md) | System architecture (event-driven, Medallion) |
| **Architecture** | [Decentralized DAGs](architecture/decentralized-dags.md) | DAG deploy convention per repo |
| **Database** | [Schema](database/schema.md) | Database tables, indexes, and queries |
| **Database** | [Migrations](database/migrations.md) | Setup and manage the database |
| **Development** | [Docker Setup](development/docker-setup.md) | Local PostgreSQL + Typesense |
| **Development** | [PostgresManager](development/postgres-manager.md) | PostgreSQL storage manager guide |
| **Typesense** | [Integration](typesense/README.md) | Search engine integration |
| **Runbooks** | [Composer Recovery](runbooks/composer-recovery.md) | Cloud Composer troubleshooting |
| **Runbooks** | [Migration Rollback](runbooks/migration-rollback.md) | Database migration rollback |
| **Migration** | [Performance](migration/performance-optimization.md) | Performance optimization notes |

---

## Documentation Structure

```
docs/
├── README.md                           # This file (index)
├── architecture/
│   ├── overview.md                     # System architecture
│   └── decentralized-dags.md           # DAG deploy convention
├── database/
│   ├── schema.md                       # Database schema reference
│   └── migrations.md                   # Database setup and migrations
├── development/
│   ├── setup.md                        # Development environment setup
│   ├── docker-setup.md                 # Docker (PostgreSQL + Typesense)
│   └── postgres-manager.md             # PostgresManager guide
├── migration/
│   └── performance-optimization.md     # Performance tuning notes
├── runbooks/
│   ├── composer-recovery.md            # Cloud Composer recovery
│   └── migration-rollback.md           # Migration rollback procedures
└── typesense/
    ├── README.md                       # Typesense overview
    ├── setup.md                        # Server configuration
    ├── development.md                  # Local development
    └── data-management.md              # Data workflows
```

---

## For Developers

### First Time Setup

1. **Read**: [Development Setup](development/setup.md)
2. **Install**: Python 3.12+, Poetry, Docker
3. **Setup**: `poetry install && pre-commit install && make docker-up`
4. **Test**: `pytest` to verify installation

### Daily Workflow

1. Create feature branch: `git checkout -b feat/my-feature`
2. Make changes and write tests
3. Run quality checks: `make lint && pytest`
4. Commit and push (pre-commit runs automatically)

### Key Commands

```bash
make help         # List all available commands
make docker-up    # Start PostgreSQL + Typesense
make lint         # Run linters
make test         # Run tests
```

---

## For Operators

### Runbooks

- [Composer Recovery](runbooks/composer-recovery.md) — When DAGs disappear from Airflow
- [Migration Rollback](runbooks/migration-rollback.md) — Rolling back database migrations

### Monitoring

- Airflow UI: Cloud Composer web interface
- BigQuery: dataset `dgb_gold` for analytics
- Workers: Cloud Run logs and metrics

---

## External Resources

- [Cloud SQL Documentation](https://cloud.google.com/sql/docs/postgres)
- [Cloud Composer Docs](https://cloud.google.com/composer/docs)
- [Typesense Documentation](https://typesense.org/docs/)
- [BigQuery Docs](https://cloud.google.com/bigquery/docs)

---

**Last updated**: 2026-05-13
