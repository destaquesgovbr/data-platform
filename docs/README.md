# Documentation

Comprehensive documentation for the DestaquesGovBr Data Platform.

---

## Quick Links

| Category | Document | Description |
|----------|----------|-------------|
| **Getting Started** | [Development Setup](development/setup.md) | Set up your development environment |
| **Development** | [PostgresManager](development/postgres-manager.md) | PostgreSQL storage manager guide |
| **Architecture** | [Overview](architecture/overview.md) | System architecture and design |
| **Database** | [Schema](database/schema.md) | Database tables, indexes, and queries |
| **Database** | [Migrations](database/migrations.md) | Setup and manage the database |
| **Migration** | [Plan](../_plan/README.md) | HuggingFace → PostgreSQL migration plan |
| **Migration** | [Progress](../_plan/PROGRESS.md) | Migration progress log |

---

## Documentation Structure

```
docs/
├── README.md                      # This file
├── architecture/
│   └── overview.md               # System architecture
├── database/
│   ├── schema.md                 # Database schema reference
│   └── migrations.md             # Database setup and migrations
└── development/
    └── setup.md                  # Development environment setup
```

---

## For Developers

### First Time Setup

1. **Read**: [Development Setup](development/setup.md)
2. **Install**: Python 3.11+, Poetry, gcloud CLI
3. **Setup**: Run `poetry install` and `./scripts/setup_database.sh`
4. **Test**: Run `pytest` to verify installation

### Daily Workflow

1. Create feature branch: `git checkout -b feat/my-feature`
2. Make changes and write tests
3. Run quality checks: `black . && ruff . && mypy src/ && pytest`
4. Commit and push: `git commit -m "feat: description"`

### Working with Database

- **Connect**: See [Migrations Guide](database/migrations.md#connect-to-database)
- **Schema**: See [Database Schema](database/schema.md)
- **Queries**: See [Common Queries](database/schema.md#common-queries)

---

## For Architects

### System Design

- **Architecture Overview**: [overview.md](architecture/overview.md)
- **Migration Strategy**: [Migration Plan](../_plan/README.md)
- **Design Decisions**: [ADRs](../_plan/DECISIONS.md)

### Key Concepts

1. **Partial Normalization**: Balance between normalization and performance
2. **Gradual Migration**: Minimize risk with phased approach
3. **Dual-Write**: Transition period writing to both stores
4. **Storage Adapter**: Abstraction for swapping backends

---

## For Database Administrators

### Database Reference

- **Schema**: [Database Schema](database/schema.md)
- **Migrations**: [Migrations Guide](database/migrations.md)
- **Cloud SQL Docs**: [Cloud SQL](../../infra/docs/cloud-sql.md)

### Operations

- **Setup**: [Initial Setup](database/migrations.md#initial-setup)
- **Backup**: [Backup Database](database/migrations.md#backup-database)
- **Monitoring**: [Performance Monitoring](database/migrations.md#performance-monitoring)
- **Troubleshooting**: [Troubleshooting](database/migrations.md#troubleshooting)

---

## Migration Documentation

The migration from HuggingFace to PostgreSQL is documented in [`_plan/`](../_plan):

| Document | Purpose |
|----------|---------|
| [README.md](../_plan/README.md) | Migration plan with 6 phases |
| [PROGRESS.md](../_plan/PROGRESS.md) | Progress log and timeline |
| [DECISIONS.md](../_plan/DECISIONS.md) | Architecture Decision Records (ADRs) |
| [CHECKLIST.md](../_plan/CHECKLIST.md) | Verification checklist per phase |
| [CONTEXT.md](../_plan/CONTEXT.md) | Technical context for LLMs |
| [SCHEMA.md](../_plan/SCHEMA.md) | Detailed schema design |

**Current Status**: Phase 1 Complete ✅ (Infrastructure provisioned)

---

## Project Context

### What is DestaquesGovBr?

A data platform aggregating news from ~158 Brazilian government agencies:
- Scrapes RSS feeds
- Enriches with AI summaries (Cogfy)
- Classifies into theme taxonomy
- Distributes via HuggingFace, Typesense, and website

### Why PostgreSQL?

Migrating from HuggingFace Dataset to PostgreSQL for:
- Better query capabilities
- Transactional support
- Reduced external dependencies
- Full-text search
- Structured schema

HuggingFace becomes output-only (daily sync for open data distribution).

### Repository Structure

```
destaquesgovbr/
├── infra/                    # Infrastructure (Terraform)
│   └── terraform/
│       └── cloud_sql.tf      # Cloud SQL configuration
├── data-platform/            # This repository
│   ├── docs/                 # Documentation (you are here)
│   ├── _plan/                # Migration plan
│   ├── src/                  # Source code
│   ├── tests/                # Tests
│   └── scripts/              # Utility scripts
└── [other repos...]
```

---

## Contributing

### Adding Documentation

1. Choose appropriate directory:
   - `architecture/`: System design, architecture
   - `database/`: Schema, migrations, SQL
   - `development/`: Dev guides, workflows

2. Create markdown file with clear structure
3. Update this index (docs/README.md)
4. Use relative links

### Documentation Style

- **Concise**: Brief, to the point
- **Practical**: Include code examples
- **Structured**: Use headers, tables, code blocks
- **Linked**: Cross-reference related docs

---

## External Resources

- [Cloud SQL Documentation](https://cloud.google.com/sql/docs/postgres)
- [HuggingFace Datasets](https://huggingface.co/docs/datasets)
- [PostgreSQL 15 Docs](https://www.postgresql.org/docs/15/)
- [SQLAlchemy 2.0 Docs](https://docs.sqlalchemy.org/en/20/)

---

**Last updated**: 2024-12-24
