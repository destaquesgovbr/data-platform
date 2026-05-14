# Typesense Integration

Documentação do módulo Typesense integrado ao data-platform.

## Visão Geral

O Typesense é usado como motor de busca para as notícias do DestaquesGovBr, oferecendo:
- Busca textual rápida (full-text search)
- Busca semântica via embeddings (768 dimensões)
- Facetas para filtros (agência, tema, ano, mês)
- API REST para o portal

## Arquitetura

```
PostgreSQL                    Typesense Server
┌──────────────┐             ┌──────────────┐
│ news         │             │              │
│ news_themes  │ ──sync──>   │ Collection:  │
│ news_embed.  │             │   news       │
└──────────────┘             └──────────────┘
       ↑                            ↓
   data-platform               Portal API
   (CLI/Workflows)             (Cloud Run)
```

## Documentação

| Documento | Descrição |
|-----------|-----------|
| [setup.md](./setup.md) | Configuração do servidor Typesense |
| [development.md](./development.md) | Desenvolvimento local e API keys |
| [data-management.md](./data-management.md) | Workflows e comandos CLI |

## Comandos CLI

```bash
# Sincronizar dados do PostgreSQL para Typesense
poetry run data-platform sync-typesense --start-date 2025-01-01

# Listar collections
poetry run data-platform typesense-list

# Deletar collection
poetry run data-platform typesense-delete --confirm
```

## Workflows

| Workflow | Descrição | Trigger |
|----------|-----------|---------|
| `typesense-sync-worker-deploy.yaml` | Deploy do Typesense Sync Worker | Push to main |
| `typesense-maintenance-sync.yaml` | Sync de manutenção (batch) | Manual |
| `typesense-schema-update.yaml` | Atualização de schema da collection | Manual |

### Sync Event-Driven (principal)

O **Typesense Sync Worker** (Cloud Run) recebe mensagens Pub/Sub dos topics `dgb.news.enriched` e `dgb.news.embedded`, fazendo upsert em tempo real no Typesense. Este é o mecanismo principal de sincronização.

Os workflows manuais (`maintenance-sync`, `schema-update`) são usados apenas para operações de manutenção ou correção.

## Estrutura do Código

```
src/data_platform/
├── typesense/           # Módulo core
│   ├── client.py        # Conexão com Typesense
│   ├── collection.py    # Schema da collection
│   ├── indexer.py       # Indexação de documentos
│   └── utils.py         # Utilitários
└── jobs/typesense/      # Jobs de sincronização
    ├── sync_job.py      # Job principal: PG → Typesense
    └── collection_ops.py # Operações de collection
```

## Schema da Collection

A collection `news` contém:
- Campos de texto: `title`, `content`, `summary`
- Facetas: `agency`, `category`, `theme_*`
- Datas: `published_at`, `extracted_at`
- Embedding: `content_embedding` (768 dims)

Ver detalhes completos em [setup.md](./setup.md#schema-da-collection).

## Variáveis de Ambiente

```bash
TYPESENSE_HOST=34.39.186.38
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=<sua-api-key>
DATABASE_URL=postgresql://...
```

## Links Úteis

- [Typesense Documentation](https://typesense.org/docs/)
- [Typesense API Reference](https://typesense.org/docs/latest/api/)
