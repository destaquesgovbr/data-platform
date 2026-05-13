# Docker Configuration

Configuração Docker para desenvolvimento local e workers Cloud Run.

---

## Estrutura

```
docker/
├── README.md                  # Este arquivo
├── postgres/
│   └── init.sql               # Schema inicial do PostgreSQL
├── bronze-writer/
│   └── Dockerfile             # Bronze Writer (Cloud Run)
├── feature-worker/
│   └── Dockerfile             # Feature Worker (Cloud Run)
├── thumbnail-worker/
│   └── Dockerfile             # Thumbnail Worker (Cloud Run)
└── typesense-sync-worker/
    └── Dockerfile             # Typesense Sync Worker (Cloud Run)
```

---

## Docker Compose (dev local)

O `docker-compose.yml` na raiz do projeto inclui:

| Serviço | Imagem | Porta | Descrição |
|---------|--------|-------|-----------|
| PostgreSQL | `postgres:15` | 5433 | Banco de desenvolvimento |
| Typesense | `typesense/typesense:27.1` | 8108 | Motor de busca local |

```bash
# Iniciar todos os serviços
make docker-up

# Parar
make docker-down

# Conectar ao PostgreSQL
make psql

# Popular dados mestres
make populate-master
```

---

## Workers (Cloud Run)

Cada worker tem seu próprio Dockerfile usado pelo CI/CD para build e deploy:

| Worker | Dockerfile | Deploy Workflow |
|--------|-----------|-----------------|
| feature-worker | `docker/feature-worker/Dockerfile` | `feature-worker-deploy.yaml` |
| thumbnail-worker | `docker/thumbnail-worker/Dockerfile` | `thumbnail-worker-deploy.yaml` |
| typesense-sync-worker | `docker/typesense-sync-worker/Dockerfile` | `typesense-sync-worker-deploy.yaml` |

Os Dockerfiles compartilham padrão comum:
1. Base image Python 3.12-slim
2. Install dependencies via Poetry (export → pip install)
3. Copy source code
4. Run with uvicorn

---

## PostgreSQL

### init.sql

Script SQL executado automaticamente na primeira inicialização do container PostgreSQL.

**Conteúdo**:
- Criação de tabelas (agencies, themes, news, news_features)
- Índices para performance
- Triggers para auto-update de timestamps
- Constraints e foreign keys

**Execução**:
- Automática via `docker-entrypoint-initdb.d/`
- Roda apenas na primeira vez (quando volume está vazio)
- Para re-executar: `docker-compose down -v && docker-compose up -d`

---

## Variáveis de Ambiente

Definidas em `.env` (copiar de `.env.example`):

```bash
POSTGRES_USER=destaquesgovbr_dev
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=destaquesgovbr_dev
POSTGRES_PORT=5433
```

---

## Troubleshooting

### Container não inicia

```bash
docker-compose logs postgres
docker-compose logs typesense
lsof -i :5433
lsof -i :8108
```

### Recriar do zero

```bash
docker-compose down -v
docker-compose up -d
```

---

Ver [docs/development/docker-setup.md](../docs/development/docker-setup.md) para guia completo de desenvolvimento local.

**Última atualização**: 2026-05-13
