# Contexto Técnico para LLMs

> **Propósito**: Este documento fornece contexto completo para assistentes de IA (LLMs) que ajudam na implementação deste projeto. Leia este documento no início de cada sessão de trabalho.

---

## O Que É Este Projeto

**DestaquesGovBr** é uma plataforma que agrega notícias de ~160 sites governamentais brasileiros (gov.br). O sistema:

1. **Coleta** notícias diariamente via scrapers
2. **Enriquece** com classificação temática via IA (Cogfy)
3. **Armazena** em um dataset público no HuggingFace
4. **Indexa** no Typesense para busca full-text
5. **Exibe** em um portal web (Next.js)

**Problema atual**: O HuggingFace Dataset está sendo usado como banco de dados principal (inserts, updates), mas não foi projetado para isso. Limitações: sem transações, updates caros, sem queries complexas.

**Solução**: Migrar para PostgreSQL como fonte de verdade, mantendo HuggingFace como output de dados abertos.

---

## Arquitetura Atual (Antes da Migração)

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE DIÁRIO (4 AM UTC)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
     ┌────────────────────────┼────────────────────────┐
     │                        │                        │
     ▼                        ▼                        ▼
┌─────────┐            ┌─────────────┐          ┌─────────────┐
│ Gov.br  │            │    EBC      │          │   Cogfy     │
│ Scraper │            │   Scraper   │          │ (AI enrich) │
└────┬────┘            └──────┬──────┘          └──────┬──────┘
     │                        │                        │
     └────────────────────────┼────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │   HuggingFace Dataset  │  ← FONTE DE VERDADE (atual)
                 │  nitaibezerra/govbrnews│
                 │     (~300k registros)  │
                 └────────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   ┌──────────┐        ┌──────────┐          ┌──────────┐
   │ Typesense│        │  Qdrant  │          │  Portal  │
   │ (search) │        │ (vectors)│          │ (Next.js)│
   └──────────┘        └──────────┘          └──────────┘
```

---

## Arquitetura Alvo (Após Migração)

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE DIÁRIO (4 AM UTC)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                 ┌────────────────────────┐
                 │      PostgreSQL        │  ← NOVA FONTE DE VERDADE
                 │      (Cloud SQL)       │
                 │     (~300k registros)  │
                 └────────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   ┌──────────┐        ┌──────────┐          ┌───────────────┐
   │ Typesense│        │  Qdrant  │          │  HuggingFace  │
   │ (search) │        │ (vectors)│          │ (dados abertos)│
   └──────────┘        └──────────┘          └───────────────┘
```

---

## Repositórios Relevantes

| Repositório | Caminho Local | Descrição |
|-------------|---------------|-----------|
| **data-platform** | `/destaquesgovbr/data-platform` | NOVO - Código de dados (este repo) |
| **infra** | `/destaquesgovbr/infra` | Terraform (privado) |
| **scraper** | `/destaquesgovbr/scraper` | Scrapers atuais (será migrado) |
| **portal** | `/destaquesgovbr/portal` | Frontend Next.js |
| **typesense** | `/destaquesgovbr/typesense` | Loader do Typesense |
| **agencies** | `/destaquesgovbr/agencies` | Dados de agências (agencies.yaml) |
| **themes** | `/destaquesgovbr/themes` | Árvore temática (themes_tree.yaml) |

**Caminho base**: `/Users/nitai/Dropbox/dev-mgi/destaquesgovbr/`

---

## Arquivos Críticos

### Produtores de Dados (Escrita no HF)

```
/destaquesgovbr/scraper/src/dataset_manager.py
├── DatasetManager.insert()      # Insere novas notícias
├── DatasetManager.update()      # Atualiza enriquecimentos
└── DatasetManager._push_dataset_to_hub()  # Push para HF

/destaquesgovbr/scraper/src/enrichment_manager.py
├── EnrichmentManager._load_dataset_from_huggingface()
└── EnrichmentManager._upload_enriched_dataset()
```

### Consumidores de Dados (Leitura do HF)

```
/destaquesgovbr/typesense/src/typesense_dgb/dataset.py
└── download_and_process_dataset()  # Carrega para indexar

/govbrnews-qdrant/scripts/generate-embeddings.py
└── Carrega dataset para gerar embeddings
```

### Workflows (CI/CD)

```
/destaquesgovbr/scraper/.github/workflows/
├── main-workflow.yaml      # Pipeline principal (4 AM UTC)
├── pipeline-steps.yaml     # Jobs: scraper, cogfy, enrich
└── scraper-dispatch.yaml   # Execução manual
```

### Dados Mestres

```
/destaquesgovbr/agencies/agencies.yaml
└── 158 agências governamentais

/destaquesgovbr/themes/themes_tree.yaml
└── Árvore hierárquica de temas (3 níveis)
```

---

## Schema dos Dados

### Campos do Dataset Atual (HuggingFace)

| Campo | Tipo | Obrigatório | Fonte |
|-------|------|-------------|-------|
| `unique_id` | string | Sim | Scraper (MD5) |
| `agency` | string | Sim | Scraper |
| `published_at` | datetime | Sim | Scraper |
| `title` | string | Sim | Scraper |
| `url` | string | Sim | Scraper |
| `content` | string | Não | Scraper |
| `image` | string | Não | Scraper |
| `category` | string | Não | Scraper |
| `tags` | list | Não | Scraper |
| `extracted_at` | datetime | Sim | Scraper |
| `theme_1_level_1_code` | string | Não | Cogfy |
| `theme_1_level_1_label` | string | Não | Cogfy |
| `theme_1_level_2_code` | string | Não | Cogfy |
| `theme_1_level_2_label` | string | Não | Cogfy |
| `theme_1_level_3_code` | string | Não | Cogfy |
| `theme_1_level_3_label` | string | Não | Cogfy |
| `most_specific_theme_code` | string | Não | EnrichmentManager |
| `most_specific_theme_label` | string | Não | EnrichmentManager |
| `summary` | string | Não | Cogfy |

### Schema PostgreSQL (Alvo)

Ver [SCHEMA.md](./SCHEMA.md) para o schema completo.

**Tabelas principais**:
- `agencies` (dados mestres de agências)
- `themes` (hierarquia de temas)
- `news` (notícias - tabela principal)
- `sync_log` (log de sincronizações)

---

## Decisões Arquiteturais Já Tomadas

1. **Banco de dados**: PostgreSQL (Cloud SQL)
2. **Sync HuggingFace**: Diário (não em tempo real)
3. **Schema**: Parcialmente normalizado (agencies e themes separados)
4. **Migração**: Gradual com período de dual-write
5. **Repositório**: Monorepo data-platform para código Python
6. **Terraform**: Permanece no repo infra (privado)

Ver [DECISIONS.md](./DECISIONS.md) para detalhes.

---

## Variáveis de Ambiente

### Atuais (HuggingFace)

```bash
HF_TOKEN=xxx                    # Token de escrita no HuggingFace
COGFY_API_KEY=xxx               # API key do Cogfy
COGFY_COLLECTION_ID=xxx         # ID da collection no Cogfy
```

### Novas (PostgreSQL)

```bash
DATABASE_URL=postgresql://...   # Connection string completa
STORAGE_BACKEND=huggingface     # huggingface | postgres | dual_write
STORAGE_READ_FROM=huggingface   # De onde ler em dual_write
```

---

## Comandos Úteis

### Pipeline Atual (Scraper)

```bash
# Scraping
python src/main.py scrape --start-date 2024-01-01 --end-date 2024-01-01

# Upload para Cogfy
python src/upload_to_cogfy_manager.py --start-date 2024-01-01

# Enriquecimento
python src/enrichment_manager.py --start-date 2024-01-01
```

### Typesense

```bash
# Indexação completa
python init-typesense.py --mode full

# Indexação incremental
python init-typesense.py --mode incremental --days 7
```

---

## Padrões de Código

### Estilo

- Python 3.11+
- Type hints obrigatórios
- Docstrings no formato Google
- Black para formatação
- Ruff para linting

### Estrutura de Classes

```python
class PostgresManager:
    """
    Gerencia operações no PostgreSQL.

    Interface compatível com DatasetManager para facilitar migração.
    """

    def __init__(self, connection_string: str | None = None):
        """Inicializa conexão com o banco."""
        ...

    def insert(self, new_data: OrderedDict, allow_update: bool = False) -> int:
        """
        Insere novos registros.

        Args:
            new_data: Dados a inserir
            allow_update: Se True, atualiza registros existentes

        Returns:
            Número de registros inseridos/atualizados
        """
        ...
```

---

## Checklist para Novas Sessões

Ao iniciar uma nova sessão de trabalho:

1. [ ] Leia este arquivo (CONTEXT.md)
2. [ ] Verifique [PROGRESS.md](./PROGRESS.md) para estado atual
3. [ ] Consulte [DECISIONS.md](./DECISIONS.md) para decisões passadas
4. [ ] Verifique [CHECKLIST.md](./CHECKLIST.md) para próximas tarefas

---

## Contatos e Recursos

- **HuggingFace Dataset**: https://huggingface.co/datasets/nitaibezerra/govbrnews
- **Portal**: https://destaques.gov.br (ou Cloud Run URL)
- **Documentação**: `/Users/nitai/Dropbox/dev-mgi/docs/`

---

*Última atualização: 2024-12-24*
