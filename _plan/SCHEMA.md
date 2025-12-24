# Schema PostgreSQL - GovBRNews

> **Versão**: 1.0
> **Database**: govbrnews
> **Encoding**: UTF-8
> **Timezone**: UTC

---

## Visão Geral

O schema é **parcialmente normalizado**:
- **Tabelas normalizadas**: `agencies`, `themes` (dados mestres)
- **Tabela principal**: `news` (com FKs e alguns campos denormalizados)
- **Tabela auxiliar**: `sync_log` (rastreamento de sincronizações)

---

## Diagrama Entidade-Relacionamento

```
┌──────────────┐         ┌───────────────┐
│   agencies   │         │    themes     │
│──────────────│         │───────────────│
│ id (PK)      │         │ id (PK)       │
│ key (UNIQUE) │         │ code (UNIQUE) │
│ name         │◄─┐      │ label         │◄─┐
│ type         │  │      │ level         │  │
│ parent_key   │  │      │ parent_code   │──┘
│ url          │  │      │ full_name     │
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
            │ agency_id (FK → agencies)             │
            │ theme_l1_id (FK → themes)             │
            │ theme_l2_id (FK → themes)             │
            │ theme_l3_id (FK → themes)             │
            │ most_specific_theme_id (FK → themes)  │
            │ title, content, url, ...              │
            │ agency_key, agency_name (denorm)      │
            │ published_at, created_at, ...         │
            │ synced_to_hf_at                       │
            └───────────────────────────────────────┘

                  ┌───────────────┐
                  │   sync_log    │
                  │───────────────│
                  │ id (PK)       │
                  │ operation     │
                  │ status        │
                  │ started_at    │
                  │ ...           │
                  └───────────────┘
```

---

## Tabela: agencies

Armazena dados mestres das agências governamentais.

### Schema

```sql
CREATE TABLE agencies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100),
    parent_key VARCHAR(100),
    url VARCHAR(1000),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Índices

```sql
CREATE INDEX idx_agencies_key ON agencies(key);
CREATE INDEX idx_agencies_parent ON agencies(parent_key);
```

### Colunas

| Coluna | Tipo | Obrigatório | Descrição | Exemplo |
|--------|------|-------------|-----------|---------|
| id | SERIAL | Sim | Primary key | 1 |
| key | VARCHAR(100) | Sim | Identificador único | "mec" |
| name | VARCHAR(500) | Sim | Nome completo | "Ministério da Educação" |
| type | VARCHAR(100) | Não | Tipo de órgão | "Ministério", "Agência" |
| parent_key | VARCHAR(100) | Não | Órgão superior | "presidencia" |
| url | VARCHAR(1000) | Não | URL do feed | "https://..." |
| created_at | TIMESTAMPTZ | Sim | Data de criação | 2024-01-01 00:00:00+00 |
| updated_at | TIMESTAMPTZ | Sim | Última atualização | 2024-01-01 00:00:00+00 |

### Dados de Exemplo

```sql
INSERT INTO agencies (key, name, type, url) VALUES
('mec', 'Ministério da Educação', 'Ministério', 'https://www.gov.br/mec/...'),
('saude', 'Ministério da Saúde', 'Ministério', 'https://www.gov.br/saude/...'),
('gestao', 'Ministério da Gestão e da Inovação em Serviços Públicos', 'Ministério', '...');
```

### População Inicial

Dados carregados de: `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/agencies/agencies.yaml`

Total esperado: ~158 agências

---

## Tabela: themes

Armazena a taxonomia hierárquica de temas (3 níveis).

### Schema

```sql
CREATE TABLE themes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    label VARCHAR(500) NOT NULL,
    full_name VARCHAR(600),
    level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT fk_parent_theme FOREIGN KEY (parent_code) 
        REFERENCES themes(code) ON DELETE SET NULL
);
```

### Índices

```sql
CREATE INDEX idx_themes_code ON themes(code);
CREATE INDEX idx_themes_level ON themes(level);
CREATE INDEX idx_themes_parent ON themes(parent_code);
```

### Colunas

| Coluna | Tipo | Obrigatório | Descrição | Exemplo |
|--------|------|-------------|-----------|---------|
| id | SERIAL | Sim | Primary key | 1 |
| code | VARCHAR(20) | Sim | Código hierárquico | "01.01.01" |
| label | VARCHAR(500) | Sim | Nome do tema | "Política Fiscal" |
| full_name | VARCHAR(600) | Não | Código + Label | "01.01.01 - Política Fiscal" |
| level | SMALLINT | Sim | Nível (1, 2 ou 3) | 3 |
| parent_code | VARCHAR(20) | Não | Código do tema pai | "01.01" |
| created_at | TIMESTAMPTZ | Sim | Data de criação | 2024-01-01 00:00:00+00 |

### Hierarquia

```
Level 1: "01" - Economia e Finanças
    ↓
Level 2: "01.01" - Política Econômica
    ↓
Level 3: "01.01.01" - Política Fiscal
```

### Dados de Exemplo

```sql
-- Level 1
INSERT INTO themes (code, label, full_name, level, parent_code) VALUES
('01', 'Economia e Finanças', '01 - Economia e Finanças', 1, NULL);

-- Level 2
INSERT INTO themes (code, label, full_name, level, parent_code) VALUES
('01.01', 'Política Econômica', '01.01 - Política Econômica', 2, '01');

-- Level 3
INSERT INTO themes (code, label, full_name, level, parent_code) VALUES
('01.01.01', 'Política Fiscal', '01.01.01 - Política Fiscal', 3, '01.01');
```

### População Inicial

Dados carregados de: `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/themes/themes_tree.yaml`

Total esperado: ~150-200 temas (25 L1, ~100 L2, ~50-75 L3)

---

## Tabela: news

Tabela principal que armazena todas as notícias.

### Schema

```sql
CREATE TABLE news (
    id SERIAL PRIMARY KEY,
    unique_id VARCHAR(32) UNIQUE NOT NULL,
    
    -- Foreign keys
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    theme_l1_id INTEGER REFERENCES themes(id),
    theme_l2_id INTEGER REFERENCES themes(id),
    theme_l3_id INTEGER REFERENCES themes(id),
    most_specific_theme_id INTEGER REFERENCES themes(id),
    
    -- Core content
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    category VARCHAR(500),
    tags TEXT[],
    content TEXT,
    editorial_lead TEXT,
    subtitle TEXT,
    
    -- AI-generated content
    summary TEXT,
    
    -- Timestamps
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime TIMESTAMP WITH TIME ZONE,
    extracted_at TIMESTAMP WITH TIME ZONE,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    synced_to_hf_at TIMESTAMP WITH TIME ZONE,
    
    -- Denormalized fields (for query performance)
    agency_key VARCHAR(100),
    agency_name VARCHAR(500)
);
```

### Índices

```sql
-- Primary lookup
CREATE UNIQUE INDEX idx_news_unique_id ON news(unique_id);

-- Date queries (most common)
CREATE INDEX idx_news_published_at ON news(published_at DESC);
CREATE INDEX idx_news_published_date ON news(DATE(published_at));

-- Agency filtering
CREATE INDEX idx_news_agency_id ON news(agency_id);
CREATE INDEX idx_news_agency_key ON news(agency_key);

-- Theme filtering
CREATE INDEX idx_news_theme_l1 ON news(theme_l1_id);
CREATE INDEX idx_news_most_specific_theme ON news(most_specific_theme_id);

-- Sync tracking
CREATE INDEX idx_news_synced_to_hf ON news(synced_to_hf_at) 
    WHERE synced_to_hf_at IS NULL;

-- Composite indexes for common patterns
CREATE INDEX idx_news_agency_date ON news(agency_id, published_at DESC);
CREATE INDEX idx_news_date_range ON news(published_at) 
    WHERE published_at >= NOW() - INTERVAL '1 year';

-- Full-text search (Portuguese)
CREATE INDEX idx_news_fts ON news 
    USING GIN (to_tsvector('portuguese', title || ' ' || COALESCE(content, '')));
```

### Colunas

| Coluna | Tipo | Obrigatório | Descrição | Origem |
|--------|------|-------------|-----------|--------|
| id | SERIAL | Sim | Primary key | Auto |
| unique_id | VARCHAR(32) | Sim | MD5(agency+published_at+title) | Scraper |
| agency_id | INTEGER | Sim | FK para agencies | Scraper |
| theme_l1_id | INTEGER | Não | FK para theme L1 | Cogfy |
| theme_l2_id | INTEGER | Não | FK para theme L2 | Cogfy |
| theme_l3_id | INTEGER | Não | FK para theme L3 | Cogfy |
| most_specific_theme_id | INTEGER | Não | FK para tema mais específico | EnrichmentManager |
| title | TEXT | Sim | Título da notícia | Scraper |
| url | TEXT | Não | URL original | Scraper |
| image_url | TEXT | Não | URL da imagem | Scraper |
| category | VARCHAR(500) | Não | Categoria original | Scraper |
| tags | TEXT[] | Não | Tags/palavras-chave | Scraper |
| content | TEXT | Não | Conteúdo em Markdown | Scraper |
| editorial_lead | TEXT | Não | Linha fina | Scraper |
| subtitle | TEXT | Não | Subtítulo | Scraper |
| summary | TEXT | Não | Resumo gerado por IA | Cogfy |
| published_at | TIMESTAMPTZ | Sim | Data de publicação | Scraper |
| updated_datetime | TIMESTAMPTZ | Não | Data de atualização | Scraper |
| extracted_at | TIMESTAMPTZ | Não | Data de extração | Scraper |
| created_at | TIMESTAMPTZ | Sim | Criado no BD em | Auto |
| updated_at | TIMESTAMPTZ | Sim | Atualizado no BD em | Auto |
| synced_to_hf_at | TIMESTAMPTZ | Não | Última sync para HF | HFSyncJob |
| agency_key | VARCHAR(100) | Não | Chave da agência (denorm) | Trigger |
| agency_name | VARCHAR(500) | Não | Nome da agência (denorm) | Trigger |

### Triggers

```sql
-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Denormalize agency info
CREATE OR REPLACE FUNCTION denormalize_agency_info()
RETURNS TRIGGER AS $$
BEGIN
    SELECT key, name INTO NEW.agency_key, NEW.agency_name
    FROM agencies WHERE id = NEW.agency_id;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER denormalize_news_agency
    BEFORE INSERT OR UPDATE OF agency_id ON news
    FOR EACH ROW
    EXECUTE FUNCTION denormalize_agency_info();
```

---

## Tabela: sync_log

Rastreia operações de sincronização (para HuggingFace, Typesense, etc).

### Schema

```sql
CREATE TABLE sync_log (
    id SERIAL PRIMARY KEY,
    operation VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_processed INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    metadata JSONB
);
```

### Índices

```sql
CREATE INDEX idx_sync_log_operation ON sync_log(operation, started_at DESC);
```

### Colunas

| Coluna | Tipo | Descrição | Valores |
|--------|------|-----------|---------|
| id | SERIAL | Primary key | Auto |
| operation | VARCHAR(50) | Tipo de operação | 'hf_export', 'typesense_index', etc |
| status | VARCHAR(20) | Status | 'started', 'completed', 'failed' |
| records_processed | INTEGER | Qtd processada | 1000 |
| records_failed | INTEGER | Qtd com erro | 5 |
| started_at | TIMESTAMPTZ | Início | 2024-01-01 06:00:00+00 |
| completed_at | TIMESTAMPTZ | Fim | 2024-01-01 06:10:00+00 |
| error_message | TEXT | Mensagem de erro | NULL ou "Connection timeout" |
| metadata | JSONB | Dados adicionais | {"batch_size": 1000, ...} |

### Exemplo de Uso

```sql
-- Registrar início de sync
INSERT INTO sync_log (operation, status) 
VALUES ('hf_export', 'started')
RETURNING id;

-- Atualizar ao completar
UPDATE sync_log 
SET status = 'completed', 
    records_processed = 1500,
    completed_at = NOW()
WHERE id = 123;
```

---

## Queries Comuns

### 1. Buscar notícias por data

```sql
SELECT 
    n.unique_id,
    n.title,
    n.agency_name,
    n.published_at,
    t.label as theme
FROM news n
LEFT JOIN themes t ON n.most_specific_theme_id = t.id
WHERE n.published_at >= '2024-01-01' 
  AND n.published_at < '2024-02-01'
ORDER BY n.published_at DESC
LIMIT 20;
```

### 2. Contar notícias por agência

```sql
SELECT 
    a.name,
    COUNT(*) as total_news
FROM news n
JOIN agencies a ON n.agency_id = a.id
WHERE n.published_at >= NOW() - INTERVAL '30 days'
GROUP BY a.name
ORDER BY total_news DESC;
```

### 3. Buscar notícias não sincronizadas

```sql
SELECT 
    unique_id,
    title,
    published_at
FROM news
WHERE synced_to_hf_at IS NULL
   OR synced_to_hf_at < updated_at
ORDER BY published_at DESC
LIMIT 1000;
```

### 4. Full-text search

```sql
SELECT 
    title,
    ts_rank(to_tsvector('portuguese', title || ' ' || content), 
            plainto_tsquery('portuguese', 'educação')) as rank
FROM news
WHERE to_tsvector('portuguese', title || ' ' || content) @@ 
      plainto_tsquery('portuguese', 'educação')
ORDER BY rank DESC
LIMIT 10;
```

### 5. Hierarquia de temas

```sql
-- Obter tema L3 com seus pais
SELECT 
    t3.code as l3_code,
    t3.label as l3_label,
    t2.code as l2_code,
    t2.label as l2_label,
    t1.code as l1_code,
    t1.label as l1_label
FROM themes t3
LEFT JOIN themes t2 ON t3.parent_code = t2.code
LEFT JOIN themes t1 ON t2.parent_code = t1.code
WHERE t3.level = 3 AND t3.code = '01.01.01';
```

---

## Manutenção

### Vacuum

```sql
-- Vacuum regular (libera espaço, atualiza estatísticas)
VACUUM ANALYZE news;

-- Vacuum full (reescreve tabela, mais lento)
VACUUM FULL news;
```

### Reindex

```sql
-- Recriar índices (se corrompidos ou desatualizados)
REINDEX TABLE news;
```

### Estatísticas

```sql
-- Ver tamanho das tabelas
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## Migração de Dados

### Ordem de População

1. `agencies` (dados mestres)
2. `themes` (dados mestres, respeitando hierarquia L1 → L2 → L3)
3. `news` (dados principais)

### Scripts

```bash
# 1. Criar schema
psql $DATABASE_URL -f scripts/create_schema.sql

# 2. Popular agencies
python scripts/populate_agencies.py

# 3. Popular themes
python scripts/populate_themes.py

# 4. Migrar news do HuggingFace
python scripts/migrate_hf_to_postgres.py --batch-size 1000
```

---

*Última atualização: 2024-12-24*
