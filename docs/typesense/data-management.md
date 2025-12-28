# Typesense Data Management

Este documento descreve os workflows e comandos disponíveis para gerenciar os dados no Typesense em produção.

## Visão Geral

O projeto possui três formas de gerenciar dados no Typesense:

1. **Daily Incremental Load** - Carregamento incremental diário automático
2. **Full Data Reload** - Recarregamento completo manual (workflow dispatcher)
3. **CLI Commands** - Comandos para operações manuais

## Fonte de Dados

Os dados são lidos do **PostgreSQL** (não mais do HuggingFace) e incluem:
- Notícias com metadados (título, conteúdo, agência, etc.)
- Temas classificados por IA (3 níveis hierárquicos)
- Embeddings semânticos (768 dimensões)

## 1. Carregamento Incremental Diário

### Descrição
Workflow que executa automaticamente todos os dias às 10:00 AM UTC (7:00 AM horário de Brasília) para carregar notícias dos últimos 7 dias.

### Workflow
`.github/workflows/typesense-daily-load.yaml`

### Execução Manual
Você pode executar manualmente via GitHub Actions:
1. Acesse: Actions → "Typesense Daily Incremental Load" → "Run workflow"
2. Opcionalmente, especifique o número de dias para carregar (padrão: 7)

### Comportamento
- Modo: `incremental`
- Ação: `upsert` (atualiza documentos existentes ou insere novos)
- Não deleta dados existentes
- Atualiza o cache do portal automaticamente após sucesso

## 2. Recarregamento Completo (Full Reload)

### OPERAÇÃO DESTRUTIVA

Este workflow **deleta completamente** a collection existente e recarrega todos os dados do zero.

### Quando Usar
- Após mudanças no schema da collection
- Para resolver problemas de dados corrompidos
- Para sincronizar com alterações no banco de dados
- Para limpar dados inconsistentes

### Workflow
`.github/workflows/typesense-full-reload.yaml`

### Como Executar

1. **Acesse o GitHub Actions**
   ```
   Repository → Actions → "Typesense Full Data Reload" → "Run workflow"
   ```

2. **Preencha os Parâmetros**
   - **confirm_deletion**: Digite exatamente `DELETE` (em maiúsculas) para confirmar
   - **start_date**: Data inicial (padrão: 2025-01-01)
   - **skip_portal_refresh**: (Opcional) Marque para não atualizar o cache do portal

3. **Confirme e Execute**
   - Clique em "Run workflow"
   - O workflow irá:
     1. Deletar a collection `news` existente
     2. Recriar a collection com o schema atualizado
     3. Carregar todos os dados do PostgreSQL
     4. Verificar a integridade dos dados
     5. Atualizar o cache do portal (se não foi pulado)

### Tempo de Execução
- Estimado: 15-30 minutos (depende do tamanho do dataset)

## 3. Comandos CLI

Para operações manuais ou debugging, você pode usar os comandos CLI do data-platform.

### Pré-requisitos
```bash
# Instalar dependências
poetry install

# Configurar variáveis de ambiente
export TYPESENSE_HOST=your-host
export TYPESENSE_PORT=8108
export TYPESENSE_API_KEY=your-api-key
export DATABASE_URL=postgresql://user:pass@host:port/db
```

### 3.1. Listar Collections

```bash
poetry run data-platform typesense-list
```

### 3.2. Deletar Collection

```bash
# Deletar com confirmação interativa
poetry run data-platform typesense-delete --collection-name news

# Deletar sem confirmação (para automação)
poetry run data-platform typesense-delete --collection-name news --confirm
```

### 3.3. Sincronizar Dados

```bash
# Carregamento incremental (período específico)
poetry run data-platform sync-typesense \
  --start-date 2025-12-01 \
  --end-date 2025-12-31

# Carregamento completo (full sync)
poetry run data-platform sync-typesense \
  --start-date 2025-01-01 \
  --full-sync

# Sem embeddings (mais rápido para testes)
poetry run data-platform sync-typesense \
  --start-date 2025-12-01 \
  --no-include-embeddings

# Limitar número de registros (para testes)
poetry run data-platform sync-typesense \
  --start-date 2025-12-01 \
  --max-records 100
```

## Variáveis de Ambiente

### Secrets do GitHub (para workflows)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: Provider de identidade do GCP
- `GCP_SERVICE_ACCOUNT`: Service account do GCP
- Typesense config: Obtido via `fetch-typesense-config` action
- Database URL: Obtido via Secret Manager (`destaquesgovbr-postgres-connection-string`)

### Arquivo .env (para desenvolvimento local)
```bash
TYPESENSE_HOST=your-typesense-host
TYPESENSE_PORT=8108
TYPESENSE_API_KEY=your-api-key-here
DATABASE_URL=postgresql://user:pass@host:port/db
```

## Troubleshooting

### Erro: "Collection already exists"
**Solução**: Use o workflow "Typesense Full Data Reload" ou delete manualmente com `typesense-delete`

### Erro: "Typesense not ready"
**Solução**:
1. Verifique se o servidor Typesense está rodando
2. Confirme que o host e porta estão corretos
3. Teste a conectividade: `curl http://<host>:8108/health`

### Erro: "Authentication failed"
**Solução**:
1. Verifique se `TYPESENSE_API_KEY` está configurada corretamente
2. Confirme que a API key tem permissões de escrita

### Erro: "Database connection failed"
**Solução**:
1. Verifique se `DATABASE_URL` está configurada corretamente
2. Confirme que o banco de dados está acessível

## Monitoramento

### Verificar Status da Collection
```bash
poetry run data-platform typesense-list
```

### Logs do Workflow
- Acesse: Actions → [nome do workflow] → [execução específica]
- Todos os logs são salvos e podem ser inspecionados

## Backup e Recuperação

O projeto **não possui backup automático** para reduzir custos, pois:
- Os dados podem ser recriados do PostgreSQL a qualquer momento
- Use o workflow "Full Data Reload" para restaurar dados do zero

## Melhores Práticas

1. **Use Incremental Load para atualizações diárias**
   - Mais rápido e eficiente
   - Não afeta dados existentes

2. **Use Full Reload apenas quando necessário**
   - Operação destrutiva
   - Requer confirmação explícita
   - Causa downtime temporário

3. **Teste em ambiente de desenvolvimento primeiro**
   - Configure uma instância Typesense local com Docker
   - Valide mudanças de schema antes de aplicar em produção

4. **Monitore os logs dos workflows**
   - Verifique se os carregamentos estão sendo bem-sucedidos
   - Investigue falhas imediatamente

## Arquitetura

```
PostgreSQL (destaquesgovbr)
    ↓
  news + news_themes + news_embeddings
    ↓
GitHub Actions Workflow
    ↓
data-platform CLI (sync-typesense)
    ↓
Typesense Collection (news)
    ↓
Cloud Run Portal (API)
```
