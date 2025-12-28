# Typesense Setup e Gerenciamento

Documentação detalhada sobre o setup, configuração e operação do Typesense.

## Arquitetura

```
┌─────────────────────────────────────────────────┐
│            GCP Compute Engine                    │
│                                                  │
│  ┌──────────────────────────────────────────┐  │
│  │  VM: destaquesgovbr-typesense            │  │
│  │  Machine: e2-medium (2 vCPU, 4GB RAM)    │  │
│  │                                           │  │
│  │  ┌────────────────────────────────────┐  │  │
│  │  │  Typesense Server 27.1             │  │  │
│  │  │  Port: 8108                        │  │  │
│  │  │  Process: systemd service          │  │  │
│  │  └────────────────────────────────────┘  │  │
│  │                                           │  │
│  │  ┌────────────────────────────────────┐  │  │
│  │  │  Data: /mnt/typesense-data/data   │  │  │
│  │  │  Disk: 50GB SSD Persistent        │  │  │
│  │  └────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
                     ▲
                     │ Port 8108 (Firewall)
                     │
              ┌──────┴──────┐
              │  Static IP   │
              │  Public      │
              └──────────────┘
```

## Configuração

### Arquivo de Configuração

Localização: `/etc/typesense/typesense-server.ini`

```ini
[server]
api-address = 0.0.0.0
api-port = 8108
data-dir = /mnt/typesense-data/data
api-key = <gerado-na-instalação>
log-dir = /var/log/typesense
enable-cors = true

# Performance tuning
thread-pool-size = 8
num-memory-shards = 4
```

### Systemd Service

Localização: `/etc/systemd/system/typesense-server.service`

```ini
[Unit]
Description=Typesense Server
After=network.target

[Service]
Type=simple
User=typesense
Group=typesense
ExecStart=/usr/bin/typesense-server --config=/etc/typesense/typesense-server.ini
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Operações Comuns

### Verificar Status

```bash
# Via gcloud
gcloud compute ssh destaquesgovbr-typesense --zone=southamerica-east1-a \
  --command="sudo systemctl status typesense-server"
```

### Ver Logs

```bash
# Logs em tempo real
gcloud compute ssh destaquesgovbr-typesense --zone=southamerica-east1-a \
  --command="sudo journalctl -u typesense-server -f"
```

### Reiniciar Serviço

```bash
gcloud compute ssh destaquesgovbr-typesense --zone=southamerica-east1-a \
  --command="sudo systemctl restart typesense-server"
```

## Schema da Collection

A collection `news` é criada com o seguinte schema:

```json
{
  "name": "news",
  "fields": [
    {"name": "unique_id", "type": "string", "facet": true},
    {"name": "agency", "type": "string", "facet": true, "optional": true},
    {"name": "published_at", "type": "int64", "facet": false},
    {"name": "title", "type": "string", "facet": false, "optional": true},
    {"name": "url", "type": "string", "facet": false, "optional": true},
    {"name": "image", "type": "string", "facet": false, "optional": true},
    {"name": "category", "type": "string", "facet": true, "optional": true},
    {"name": "content", "type": "string", "facet": false, "optional": true},
    {"name": "summary", "type": "string", "facet": false, "optional": true},
    {"name": "extracted_at", "type": "int64", "facet": false, "optional": true},
    {"name": "theme_1_level_1_code", "type": "string", "facet": true, "optional": true},
    {"name": "theme_1_level_1_label", "type": "string", "facet": true, "optional": true},
    {"name": "theme_1_level_2_code", "type": "string", "facet": true, "optional": true},
    {"name": "theme_1_level_2_label", "type": "string", "facet": true, "optional": true},
    {"name": "theme_1_level_3_code", "type": "string", "facet": true, "optional": true},
    {"name": "theme_1_level_3_label", "type": "string", "facet": true, "optional": true},
    {"name": "most_specific_theme_code", "type": "string", "facet": true, "optional": true},
    {"name": "most_specific_theme_label", "type": "string", "facet": true, "optional": true},
    {"name": "published_year", "type": "int32", "facet": true, "optional": true},
    {"name": "published_month", "type": "int32", "facet": true, "optional": true},
    {"name": "published_week", "type": "int32", "facet": true, "optional": true},
    {"name": "content_embedding", "type": "float[]", "num_dim": 768, "optional": true, "index": true}
  ],
  "default_sorting_field": "published_at"
}
```

> **Nota**: O campo `content_embedding` (768 dimensões) permite busca semântica usando embeddings gerados pelo modelo paraphrase-multilingual-mpnet-base-v2.

## Performance Tuning

### Para Dataset Grande (295k+ documentos)

Configurações recomendadas no `typesense-server.ini`:

```ini
# Threads baseado em vCPUs
thread-pool-size = 8

# Memory shards para melhor paralelização
num-memory-shards = 4

# Cache
cache-size-mb = 1024

# Logging (produção)
log-level = INFO
```

### Monitoramento de Performance

```bash
# Stats do servidor
curl "http://${TYPESENSE_HOST}:8108/stats.json" \
  -H "X-TYPESENSE-API-KEY: ${TYPESENSE_API_KEY}"

# Métricas importantes:
# - system_memory_used_bytes
# - system_disk_used_bytes
# - typesense_memory_used_bytes
```

## Segurança

### API Key Management

**Desenvolvimento:**
```bash
# Variável de ambiente local
export TYPESENSE_API_KEY="development-key"
```

**Produção (recomendado):**
```bash
# Usar Secret Manager
gcloud secrets create typesense-api-key \
  --data-file=- <<< "production-key"
```

## Troubleshooting

### Typesense não inicia

```bash
# Ver erro específico
sudo journalctl -u typesense-server -n 50

# Erros comuns:
# 1. Permissões no data-dir
sudo chown -R typesense:typesense /mnt/typesense-data/data

# 2. Porta já em uso
sudo lsof -i :8108

# 3. Configuração inválida
sudo typesense-server --config=/etc/typesense/typesense-server.ini --test
```

### Performance degradada

```bash
# Verificar uso de recursos
htop

# Verificar disco
df -h
du -sh /mnt/typesense-data/*

# Verificar memória
free -h
```

## Referências

- [Typesense Documentation](https://typesense.org/docs/)
- [Typesense API Reference](https://typesense.org/docs/latest/api/)
