# Docker Configuration

Configuração Docker para desenvolvimento local.

---

## Estrutura

```
docker/
├── README.md          # Este arquivo
└── postgres/
    └── init.sql       # Schema inicial do PostgreSQL
```

---

## PostgreSQL

### init.sql

Script SQL executado automaticamente na primeira inicialização do container PostgreSQL.

**Conteúdo**:
- Criação de tabelas (agencies, themes, news)
- Índices para performance
- Triggers para auto-update de timestamps
- Constraints e foreign keys

**Execução**:
- Automática via `docker-entrypoint-initdb.d/`
- Roda apenas na primeira vez (quando volume está vazio)
- Para re-executar: `docker-compose down -v && docker-compose up -d`

---

## Uso

Ver [docs/development/docker-setup.md](../docs/development/docker-setup.md) para guia completo.

### Quick Start

```bash
# Iniciar
docker-compose up -d

# Popular dados mestres
make populate-master

# Conectar
make psql
```

---

## Customização

### Variáveis de Ambiente

Definidas em `.env.local` (copiar de `.env.example`):

```bash
POSTGRES_USER=govbrnews_dev
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=govbrnews_dev
POSTGRES_PORT=5432
```

### Performance Tuning

Editar `docker-compose.yml`:

```yaml
environment:
  POSTGRES_SHARED_BUFFERS: 256MB     # Memória compartilhada
  POSTGRES_MAX_CONNECTIONS: 100      # Máximo de conexões
  POSTGRES_WORK_MEM: 16MB            # Memória por operação
  POSTGRES_MAINTENANCE_WORK_MEM: 64MB # Memória para manutenção
```

---

## Troubleshooting

### Container não inicia

```bash
# Ver logs
docker-compose logs postgres

# Verificar se porta está livre
lsof -i :5432

# Recriar container
docker-compose down -v
docker-compose up -d
```

### init.sql não executou

```bash
# Remover volume e recriar
docker-compose down -v
docker-compose up -d
```

### Dados não persistem

```bash
# Verificar volume
docker volume inspect destaquesgovbr-postgres-data

# Verificar se está montado corretamente
docker inspect destaquesgovbr-postgres | grep -A 5 Mounts
```

---

**Última atualização**: 2024-12-24
