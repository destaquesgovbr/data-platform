# Desenvolvimento Local com Typesense

Este documento descreve como configurar o acesso ao Typesense para desenvolvimento local.

## Parâmetros de Conexão (Read-Only)

Para desenvolvimento local, use os seguintes parâmetros de conexão:

| Parâmetro | Valor |
|-----------|-------|
| Host | `34.39.186.38` |
| Port | `8108` |
| Protocol | `http` |
| API Key | Solicite ao time de infraestrutura |

### Configuração via variáveis de ambiente

```bash
export TYPESENSE_HOST=34.39.186.38
export TYPESENSE_PORT=8108
export TYPESENSE_API_KEY=<sua-api-key>
```

### Configuração via arquivo .env

Crie um arquivo `.env` na raiz do projeto:

```env
TYPESENSE_HOST=34.39.186.38
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=<sua-api-key>
```

## Tipos de API Keys

O projeto utiliza dois tipos de API keys:

### 1. Read-Only Key (Search-Only)

- **Secret GCP**: `typesense-read-conn`
- **Permissões**: Apenas busca (`documents:search`)
- **Uso**: Portal, desenvolvedores, ambientes de desenvolvimento
- **Segurança**: Segura para expor no frontend

Esta key só permite operações de busca e não pode:
- Criar ou deletar coleções
- Inserir, atualizar ou deletar documentos
- Gerenciar outras API keys

### 2. Admin Key (Write)

- **Secret GCP**: `typesense-write-conn`
- **Permissões**: Todas as operações
- **Uso**: Workflows de carga de dados, VM Typesense
- **Segurança**: Deve ser mantida em segredo

## Obtendo a API Key

### Para desenvolvedores

1. Solicite a API key read-only ao time de infraestrutura
2. Configure no seu ambiente local conforme descrito acima

### Via GCP Secret Manager (para quem tem acesso)

```bash
# Read-only key (para desenvolvimento)
gcloud secrets versions access latest --secret=typesense-read-conn | jq -r '.apiKey'

# Admin key (apenas para operações de escrita)
gcloud secrets versions access latest --secret=typesense-write-conn | jq -r '.apiKey'
```

## Testando a conexão

```python
import typesense

client = typesense.Client({
    'nodes': [{
        'host': '34.39.186.38',
        'port': 8108,
        'protocol': 'http'
    }],
    'api_key': '<sua-api-key>',
    'connection_timeout_seconds': 10
})

# Testar busca
results = client.collections['news'].documents.search({
    'q': 'educação',
    'query_by': 'title,content'
})
print(f"Encontrados {results['found']} documentos")
```

## Usando o CLI do data-platform

O projeto oferece comandos CLI para interagir com o Typesense:

```bash
# Listar collections
poetry run data-platform typesense-list

# Sincronizar dados do PostgreSQL para Typesense
poetry run data-platform sync-typesense --start-date 2025-01-01 --end-date 2025-12-31

# Ver ajuda do comando sync
poetry run data-platform sync-typesense --help
```

## Formato dos Secrets

Os secrets no GCP Secret Manager estão no formato JSON:

```json
{
  "host": "34.39.186.38",
  "port": 8108,
  "protocol": "http",
  "apiKey": "<chave>"
}
```

## Troubleshooting

### Erro de conexão recusada

Verifique se:
1. O host e porta estão corretos
2. Você está na rede correta (VPN se necessário)
3. A API key está configurada corretamente

### Erro de permissão (403)

Se você receber erro 403 ao tentar uma operação de escrita com a key read-only, isso é esperado. A key read-only só permite buscas.

### Erro de autenticação (401)

Verifique se a API key está correta e não expirou.
