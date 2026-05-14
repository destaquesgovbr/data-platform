# Ambiente Docker Local

Guia completo para configurar ambiente de desenvolvimento local com Docker.

---

## Visão Geral

O ambiente Docker local fornece:
- **PostgreSQL 15** isolado para desenvolvimento (porta 5433)
- **Typesense 27.1** para busca local (porta 8108)
- **Dados de teste** (agencies e themes pré-populados)
- **Persistência** de dados entre reinicializações
- **Compatibilidade** total com Cloud SQL (mesma versão PG)

---

## Componentes

### docker-compose.yml
- PostgreSQL 15 (porta 5433)
- Typesense 27.1 (porta 8108)
- Volumes persistentes para dados
- Health checks configurados

### setup_local_db.sh
- Cria schema completo
- Popula agencies (159 registros)
- Popula themes (588 registros)
- Configura índices e triggers

### .env.example
- Template de variáveis de ambiente
- Connection strings
- Configurações de serviços

---

## Estrutura de Arquivos

```
data-platform/
├── docker-compose.yml           # PostgreSQL + Typesense
├── docker/                      # Dockerfiles dos workers
│   ├── postgres/                # PostgreSQL custom image
│   ├── feature-worker/
│   ├── thumbnail-worker/
│   └── typesense-sync-worker/
├── .env.example                 # Template de variáveis
├── scripts/
│   └── setup_local_db.sh       # Setup completo do banco local
└── docs/
    └── development/
        └── docker-setup.md     # Este arquivo
```

---

## Quick Start

### 1. Iniciar Serviços

```bash
# Copiar template de variáveis
cp .env.example .env

# Iniciar containers (PostgreSQL + Typesense)
make docker-up
# ou: docker-compose up -d

# Verificar logs
docker-compose logs -f
```

### 2. Setup do Banco

```bash
# Criar schema e popular dados mestres
./scripts/setup_local_db.sh

# Ou manualmente:
python scripts/create_schema.py --local
python scripts/populate_agencies.py --local
python scripts/populate_themes.py --local
```

### 3. Testar Conexão

```bash
# PostgreSQL via psql
docker exec -it destaquesgovbr-postgres psql -U destaquesgovbr_dev -d destaquesgovbr_dev

# Typesense health check
curl http://localhost:8108/health

# Via Python
PYTHONPATH=src python -c "
from data_platform.config import get_settings
settings = get_settings()
print(f'DB: {settings.database_url}')
print(f'Typesense: {settings.typesense_url}')
"
```

---

## Comandos Úteis

### Gerenciamento de Containers

```bash
# Iniciar
docker-compose up -d

# Parar
docker-compose stop

# Parar e remover
docker-compose down

# Parar e remover TUDO (incluindo volumes)
docker-compose down -v

# Ver logs
docker-compose logs -f postgres

# Status
docker-compose ps
```

### Acesso ao Banco

```bash
# Via psql no container
docker exec -it destaquesgovbr-postgres psql -U govbrnews_dev -d govbrnews_dev

# Via psql local (se instalado)
psql postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev

# Queries úteis
# SELECT COUNT(*) FROM agencies;
# SELECT COUNT(*) FROM themes;
# SELECT COUNT(*) FROM news;
```

### Backup e Restore

```bash
# Backup
docker exec destaquesgovbr-postgres pg_dump -U govbrnews_dev govbrnews_dev > backup.sql

# Restore
cat backup.sql | docker exec -i destaquesgovbr-postgres psql -U govbrnews_dev -d govbrnews_dev

# Backup com compressão
docker exec destaquesgovbr-postgres pg_dump -U govbrnews_dev govbrnews_dev | gzip > backup.sql.gz
gunzip -c backup.sql.gz | docker exec -i destaquesgovbr-postgres psql -U govbrnews_dev -d govbrnews_dev
```

---

## Testes com Docker Local

### Testes de Integração

```bash
# Configurar para usar banco local
export DATABASE_URL="postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev"

# Rodar testes
PYTHONPATH=src pytest tests/integration/ -v

# Ou especificar connection string diretamente
PYTHONPATH=src pytest tests/integration/ -v --db-url postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev
```

### Teste de Migração

```bash
# Migração de teste (poucos registros)
python scripts/migrate_hf_to_postgres.py \
  --max-records 1000 \
  --batch-size 100 \
  --db-url postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev

# Validação
python scripts/validate_migration.py \
  --sample-size 50 \
  --db-url postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev
```

---

## Desenvolvimento

### Workflow Típico

1. **Iniciar ambiente**
   ```bash
   docker-compose up -d
   ```

2. **Fazer alterações no código**
   ```bash
   # Editar src/data_platform/...
   ```

3. **Testar alterações**
   ```bash
   PYTHONPATH=src pytest tests/ -v
   ```

4. **Resetar banco se necessário**
   ```bash
   docker-compose down -v
   make docker-up
   ./scripts/setup_local_db.sh
   ```

5. **Parar ambiente ao final**
   ```bash
   make docker-down
   ```

---

## Configuração

### PostgreSQL

**Versão**: 15 (mesma do Cloud SQL)

**Configurações** (docker-compose.yml):
- `shared_buffers`: 256MB
- `max_connections`: 100
- `work_mem`: 16MB
- `maintenance_work_mem`: 64MB

**Usuário/Database**:
- User: `govbrnews_dev`
- Password: `dev_password`
- Database: `govbrnews_dev`

### Variáveis de Ambiente

**.env.local**:
```bash
# PostgreSQL
POSTGRES_USER=govbrnews_dev
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=govbrnews_dev
DATABASE_URL=postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev

# Application
STORAGE_BACKEND=postgres
TESTING=1
```

---

## Troubleshooting

### Porta 5432 já está em uso

```bash
# Verificar o que está usando a porta
lsof -i :5432

# Parar PostgreSQL local se estiver rodando
brew services stop postgresql

# Ou mudar a porta no docker-compose.yml
ports:
  - "5433:5432"  # Host:Container
```

### Container não inicia

```bash
# Ver logs detalhados
docker-compose logs postgres

# Verificar se há volumes antigos
docker volume ls | grep destaquesgovbr

# Remover volumes antigos
docker-compose down -v
```

### Dados não persistem

```bash
# Verificar se volume está criado
docker volume inspect destaquesgovbr-postgres-data

# Verificar mount no container
docker inspect destaquesgovbr-postgres | grep -A 5 Mounts
```

### Permissões de acesso

```bash
# Entrar no container
docker exec -it destaquesgovbr-postgres bash

# Verificar pg_hba.conf
cat /var/lib/postgresql/data/pg_hba.conf

# Deve ter linha:
# host    all    all    0.0.0.0/0    md5
```

---

## Diferenças vs Cloud SQL

| Aspecto | Docker Local | Cloud SQL |
|---------|--------------|-----------|
| Autenticação | Password | IAM + Password |
| Acesso | localhost:5432 | Via Cloud SQL Proxy |
| Backup | Manual (pg_dump) | Automático |
| Alta disponibilidade | Não | Sim |
| Escalabilidade | Limitada ao host | Vertical scaling |
| Custo | Grátis | Pay-per-use |

---

## CI/CD

### GitHub Actions

```yaml
# .github/workflows/test.yml
services:
  postgres:
    image: postgres:15
    env:
      POSTGRES_USER: govbrnews_dev
      POSTGRES_PASSWORD: dev_password
      POSTGRES_DB: govbrnews_dev
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5

steps:
  - name: Setup database
    run: |
      python scripts/create_schema.py --local
      python scripts/populate_agencies.py --local
      python scripts/populate_themes.py --local

  - name: Run tests
    env:
      DATABASE_URL: postgresql://govbrnews_dev:dev_password@localhost:5432/govbrnews_dev
    run: |
      pytest tests/ -v
```

---

## Próximos Passos

- [ ] Adicionar pgAdmin container para UI
- [ ] Configurar Redis para cache (futuro)
- [ ] Adicionar monitoring (pg_stat_statements)
- [ ] Criar scripts de seed com dados de exemplo
- [ ] Documentar tuning de performance local

---

**Última atualização**: 2026-05-13
