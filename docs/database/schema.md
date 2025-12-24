# Database Schema

> PostgreSQL 15 | Cloud SQL | Database: `govbrnews`

## Overview

Partially normalized schema with 5 tables:
- **Master data**: `agencies`, `themes` (normalized)
- **Main table**: `news` (FKs + denormalized fields for performance)
- **Auxiliary**: `sync_log`, `schema_version`

---

## Tables

### agencies

Government agencies master data (~158 records).

```sql
CREATE TABLE agencies (
    id              SERIAL PRIMARY KEY,
    key             VARCHAR(100) UNIQUE NOT NULL,
    name            VARCHAR(500) NOT NULL,
    type            VARCHAR(100),
    parent_key      VARCHAR(100),
    url             VARCHAR(1000),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Indexes**:
- `idx_agencies_key` on `key`
- `idx_agencies_parent` on `parent_key`

**Key fields**:
- `key`: Unique identifier (e.g., "mec", "saude")
- `parent_key`: Self-reference to parent agency

---

### themes

Hierarchical taxonomy with 3 levels (L1 → L2 → L3).

```sql
CREATE TABLE themes (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20) UNIQUE NOT NULL,
    label           VARCHAR(500) NOT NULL,
    full_name       VARCHAR(600),
    level           SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code     VARCHAR(20),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT fk_parent_theme
        FOREIGN KEY (parent_code) REFERENCES themes(code) ON DELETE SET NULL
);
```

**Indexes**:
- `idx_themes_code` on `code`
- `idx_themes_level` on `level`
- `idx_themes_parent` on `parent_code`

**Key fields**:
- `code`: Hierarchical code (e.g., "01.01.01")
- `level`: 1 (top), 2 (mid), or 3 (leaf)
- `parent_code`: Self-reference for hierarchy

---

### news

Main news storage (~300k records). Partially normalized with FKs to agencies/themes + denormalized fields for performance.

```sql
CREATE TABLE news (
    id                      SERIAL PRIMARY KEY,
    unique_id               VARCHAR(32) UNIQUE NOT NULL,

    -- Foreign keys
    agency_id               INTEGER NOT NULL REFERENCES agencies(id),
    theme_l1_id             INTEGER REFERENCES themes(id),
    theme_l2_id             INTEGER REFERENCES themes(id),
    theme_l3_id             INTEGER REFERENCES themes(id),
    most_specific_theme_id  INTEGER REFERENCES themes(id),

    -- Core content
    title                   TEXT NOT NULL,
    url                     TEXT,
    image_url               TEXT,
    category                VARCHAR(500),
    tags                    TEXT[],
    content                 TEXT,
    editorial_lead          TEXT,
    subtitle                TEXT,

    -- AI-generated
    summary                 TEXT,

    -- Timestamps
    published_at            TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime        TIMESTAMP WITH TIME ZONE,
    extracted_at            TIMESTAMP WITH TIME ZONE,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    synced_to_hf_at         TIMESTAMP WITH TIME ZONE,

    -- Denormalized (performance)
    agency_key              VARCHAR(100),
    agency_name             VARCHAR(500)
);
```

**Primary indexes**:
- `idx_news_unique_id` (UNIQUE) on `unique_id`
- `idx_news_published_at` on `published_at DESC`
- `idx_news_agency_id` on `agency_id`
- `idx_news_most_specific_theme` on `most_specific_theme_id`

**Performance indexes**:
- `idx_news_agency_key` on `agency_key` (denormalized)
- `idx_news_agency_date` on `(agency_id, published_at DESC)`
- `idx_news_synced_to_hf` (partial) on `synced_to_hf_at WHERE synced_to_hf_at IS NULL`

**Full-text search**:
- `idx_news_fts` (GIN) on `to_tsvector('portuguese', title || ' ' || content)`

**Key fields**:
- `unique_id`: MD5(agency + published_at + title)
- `most_specific_theme_id`: Most granular theme (L3 > L2 > L1)
- `synced_to_hf_at`: Last sync to HuggingFace Dataset
- `agency_key`, `agency_name`: Denormalized from agencies for performance

---

### sync_log

Tracks sync operations (HuggingFace, Typesense, etc.).

```sql
CREATE TABLE sync_log (
    id                  SERIAL PRIMARY KEY,
    operation           VARCHAR(50) NOT NULL,
    status              VARCHAR(20) NOT NULL,
    records_processed   INTEGER DEFAULT 0,
    records_failed      INTEGER DEFAULT 0,
    started_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at        TIMESTAMP WITH TIME ZONE,
    error_message       TEXT,
    metadata            JSONB
);
```

**Indexes**:
- `idx_sync_log_operation` on `(operation, started_at DESC)`

**Key fields**:
- `operation`: e.g., "hf_export", "typesense_index"
- `status`: "started", "completed", "failed"
- `metadata`: JSONB for additional operation data

---

### schema_version

Tracks schema migrations.

```sql
CREATE TABLE schema_version (
    version         VARCHAR(20) PRIMARY KEY,
    applied_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    description     TEXT
);
```

**Current version**: `1.0` (initial schema)

---

## Triggers

### Auto-update timestamps

```sql
CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agencies_updated_at
    BEFORE UPDATE ON agencies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### Denormalize agency data

Automatically populates `agency_key` and `agency_name` in `news` table from `agencies`.

```sql
CREATE TRIGGER denormalize_news_agency
    BEFORE INSERT OR UPDATE OF agency_id ON news
    FOR EACH ROW EXECUTE FUNCTION denormalize_agency_info();
```

---

## Views

### news_with_themes

News with denormalized theme hierarchy for easy querying.

```sql
CREATE VIEW news_with_themes AS
SELECT
    n.id,
    n.unique_id,
    n.title,
    n.url,
    n.agency_name,
    n.published_at,
    n.summary,
    t1.label as theme_l1,
    t2.label as theme_l2,
    t3.label as theme_l3,
    COALESCE(t3.label, t2.label, t1.label) as most_specific_theme
FROM news n
LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
LEFT JOIN themes t3 ON n.theme_l3_id = t3.id;
```

### recent_syncs

Last 100 sync operations with duration.

```sql
CREATE VIEW recent_syncs AS
SELECT
    operation,
    status,
    records_processed,
    records_failed,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (completed_at - started_at)) as duration_seconds,
    error_message
FROM sync_log
ORDER BY started_at DESC
LIMIT 100;
```

---

## Entity Relationship Diagram

```
┌──────────────┐         ┌───────────────┐
│   agencies   │         │    themes     │
│──────────────│         │───────────────│
│ id (PK)      │         │ id (PK)       │
│ key (UNIQUE) │◄─┐      │ code (UNIQUE) │◄─┐
│ name         │  │      │ label         │  │
│ type         │  │      │ level (1-3)   │  │
│ parent_key   │  │      │ parent_code   │──┘
└──────────────┘  │      └───────────────┘
                  │            ▲  ▲  ▲  ▲
                  │            │  │  │  │
                  │      ┌─────┘  │  │  └─────┐
                  │      │        │  │        │
            ┌─────┴──────┴────────┴──┴────────┴─────┐
            │             news                      │
            │───────────────────────────────────────│
            │ id (PK)                               │
            │ unique_id (UNIQUE)                    │
            │ agency_id (FK)                        │
            │ theme_l1_id, theme_l2_id,             │
            │ theme_l3_id, most_specific_theme_id   │
            │ title, content, summary, ...          │
            │ agency_key, agency_name (denorm)      │
            │ published_at, synced_to_hf_at         │
            └───────────────────────────────────────┘
```

---

## Common Queries

### Get recent news by agency

```sql
SELECT * FROM news
WHERE agency_key = 'mec'
  AND published_at >= NOW() - INTERVAL '30 days'
ORDER BY published_at DESC;
```

### Get news with full theme hierarchy

```sql
SELECT * FROM news_with_themes
WHERE published_at >= '2024-01-01'
ORDER BY published_at DESC
LIMIT 100;
```

### Full-text search

```sql
SELECT title, published_at, agency_name
FROM news
WHERE to_tsvector('portuguese', title || ' ' || COALESCE(content, ''))
      @@ to_tsquery('portuguese', 'educação')
ORDER BY published_at DESC;
```

### Find unsynced records

```sql
SELECT COUNT(*) FROM news WHERE synced_to_hf_at IS NULL;
```

---

## Performance Notes

### Denormalization Strategy

The `news` table denormalizes `agency_key` and `agency_name` to avoid JOINs on high-frequency queries. This is auto-maintained by the `denormalize_news_agency` trigger.

### Index Selection

- **Date queries**: Use `idx_news_published_at` (DESC for recent-first)
- **Agency filtering**: Use `idx_news_agency_key` (denormalized, faster than JOIN)
- **Theme filtering**: Use `idx_news_most_specific_theme`
- **Composite**: Use `idx_news_agency_date` for agency + date range

### Partial Indexes

- `idx_news_synced_to_hf`: Only indexes records where `synced_to_hf_at IS NULL` to speed up sync job queries

---

See also:
- [Migrations Guide](./migrations.md)
- [Cloud SQL Documentation](../../infra/docs/cloud-sql.md)
