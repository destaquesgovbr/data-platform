# Registro de Decisões Arquiteturais (ADR)

> **Formato**: Cada decisão é documentada com contexto, opções consideradas, decisão tomada e consequências.

---

## ADR-001: Banco de Dados Principal

**Data**: 2024-12-24
**Status**: Aprovado

### Contexto

O HuggingFace Dataset está sendo usado como banco de dados principal, mas não foi projetado para operações OLTP (inserts, updates frequentes). Limitações incluem: sem transações, updates caros (reescreve dataset), sem queries complexas.

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **BigQuery** | Excelente para analytics, ML integrado, serverless | Não é OLTP, updates caros, latência alta |
| **PostgreSQL** | OLTP excelente, ACID, flexível, ecosistema maduro | Precisa gerenciar, não é serverless |
| **MongoDB** | Schema flexível, bom para documentos | Não é nativo GCP, JOINs limitados |

### Decisão

**PostgreSQL (Cloud SQL)** como banco de dados principal.

### Justificativa

1. Operações de insert/update são frequentes (diárias)
2. Schema é relativamente estável
3. Integração nativa com GCP (Cloud SQL)
4. Suporte a JSONB se precisar de flexibilidade
5. Ecossistema maduro para BI, DS, ML

### Consequências

- Precisa provisionar e gerenciar Cloud SQL
- Custo mensal fixo (~$30-70/mês)
- Necessidade de sync para HuggingFace (dados abertos)

---

## ADR-002: Sincronização com HuggingFace

**Data**: 2024-12-24
**Status**: Aprovado

### Contexto

O HuggingFace Dataset deve continuar disponível como dados abertos. Precisamos decidir a frequência de sincronização.

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Dual-write (tempo real)** | HF sempre atualizado | Complexidade, ponto de falha duplo |
| **Sync diário** | Simples, confiável | Lag de até 24h |
| **Sync semanal** | Muito simples | Lag muito grande |

### Decisão

**Sync diário** após o pipeline principal.

### Justificativa

1. Dados de notícias não são críticos em tempo real
2. Simplifica a arquitetura
3. Menos pontos de falha
4. HuggingFace é consumido principalmente para análise histórica

### Consequências

- HuggingFace terá lag de até 24h
- Job de sync adicional no pipeline
- Precisa monitorar falhas de sync

---

## ADR-003: Nível de Normalização do Schema

**Data**: 2024-12-24
**Status**: Aprovado

### Contexto

Precisamos decidir quão normalizado será o schema do PostgreSQL.

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Flat (como HF)** | Migração simples, queries simples | Redundância, inconsistências |
| **Parcialmente normalizado** | Dados mestres consistentes, queries razoáveis | Alguns JOINs necessários |
| **Totalmente normalizado** | Máxima consistência | Complexidade, muitos JOINs |

### Decisão

**Parcialmente normalizado**: Tabelas separadas para `agencies` e `themes`, mas `news` contém campos denormalizados para performance.

### Justificativa

1. Agencies e themes são dados mestres que mudam raramente
2. Evita redundância desnecessária nesses dados
3. Campos denormalizados em `news` evitam JOINs em queries frequentes
4. Triggers mantêm denormalização sincronizada

### Schema Resultante

```
agencies (id, key, name, type, parent_key, url)
themes (id, code, label, level, parent_code)
news (id, unique_id, agency_id, agency_key, agency_name, ...)
                      ↑         ↑           ↑
                      FK        denormalized campos
```

### Consequências

- Precisa manter triggers para denormalização
- Queries de leitura são simples (sem JOINs)
- Atualizações de agencies/themes requerem atualização em news

---

## ADR-004: Estrutura de Repositórios

**Data**: 2024-12-24
**Status**: Aprovado

### Contexto

Precisamos decidir onde colocar o código da data platform e o Terraform, considerando:
- Repo `infra` é privado (segurança)
- Código Python deve ser público quando possível
- Futura migração para Airflow

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Repos separados** | Clara separação | Código compartilhado difícil |
| **Monorepo completo** | Tudo junto | Expõe Terraform |
| **Híbrido** | Melhor dos dois | Dois repos para manter |

### Decisão

**Arquitetura híbrida**:
- `destaquesgovbr/infra` (privado): Todo Terraform, incluindo Cloud SQL
- `destaquesgovbr/data-platform` (público): Todo código Python

### Justificativa

1. Terraform com tfvars sensíveis permanece privado
2. Código Python pode ser aberto para comunidade
3. Facilita futura migração para Airflow
4. Separação clara de responsabilidades

### Consequências

- Dois repositórios para manter
- Coordenação necessária entre infra e código
- Secrets injetados via GitHub Actions/Secret Manager

---

## ADR-005: Estratégia de Migração

**Data**: 2024-12-24
**Status**: Aprovado

### Contexto

Precisamos migrar de HuggingFace para PostgreSQL sem downtime e com possibilidade de rollback.

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Big bang** | Rápido, simples | Alto risco, sem rollback fácil |
| **Dual-write** | Rollback fácil, validação | Mais complexo, mais tempo |
| **Shadow mode** | Baixo risco | Muito tempo, complexidade |

### Decisão

**Migração gradual com dual-write**:
1. Fase de desenvolvimento (sem impacto)
2. Dual-write com leitura do HF
3. Dual-write com leitura do PG
4. PG como primary, sync para HF

### Justificativa

1. Permite validação em cada etapa
2. Rollback simples em qualquer fase
3. Zero downtime
4. Confiança gradual no novo sistema

### Consequências

- Migração leva mais tempo (semanas)
- Período de manutenção de dois sistemas
- Precisa de validação contínua

---

## ADR-006: Airflow (Futuro)

**Data**: 2024-12-24
**Status**: Pendente

### Contexto

Há planos de migrar os workflows do GitHub Actions para Airflow.

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Cloud Composer** | Gerenciado, integrado GCP | Custo alto (~$300-400/mês) |
| **Self-hosted** | Custo baixo (~$50-100/mês) | Mais ops, manutenção |

### Decisão

**Ainda não decidido**. Será avaliado após a migração do banco de dados.

### Considerações para Decisão Futura

1. Volume de DAGs necessários
2. Complexidade de dependências
3. Necessidade de escalabilidade
4. Orçamento disponível
5. Equipe para manutenção

---

## ADR-007: Estratégia de Embeddings Semânticos

**Data**: 2024-12-26
**Status**: Aprovado

### Contexto

Para habilitar busca semântica na plataforma e potencializar recursos de IA, precisamos adicionar embeddings para notícias. Decisões críticas incluem:
1. Qual modelo de embedding usar
2. Qual texto usar como input (title, summary, content)
3. Onde armazenar os embeddings (PostgreSQL, Typesense, Qdrant)
4. **Escopo**: Quais notícias processar (todas ou apenas recentes)
5. Quando gerar no pipeline (antes ou depois do Cogfy)

**Restrição importante**: Apenas notícias de 2025 possuem resumos AI-gerados pelo Cogfy. Notícias anteriores não têm o campo `summary` preenchido.

### Opções Consideradas

#### 1. Modelo de Embedding

| Opção | Prós | Contras |
|-------|------|---------|
| **paraphrase-multilingual-mpnet-base-v2** | Já usado para temas, excelente português, local (grátis), 768 dims | Modelo mais pesado |
| **all-MiniLM-L6-v2** | Muito rápido, leve, 384 dims | Inglês-cêntrico, pior português |
| **OpenAI text-embedding-3-small** | Alta qualidade, 1536 dims | Custo ($0.02/1M tokens), API externa |

#### 2. Input para Embedding

| Opção | Prós | Contras |
|-------|------|---------|
| **title + summary** | Summary é AI-gerado (Cogfy), mais semântico | Apenas 2025 tem summary |
| **title + content** | Disponível para todas as notícias | Content tem muito ruído (HTML, listas) |
| **title only** | Simples, disponível | Perde contexto importante |

#### 3. Storage dos Embeddings

| Opção | Prós | Contras |
|-------|------|---------|
| **PostgreSQL (pgvector) + Typesense** | Queries avançadas (PG), busca rápida (Typesense), MCP Server usa Typesense | Mais complexo, 2 sistemas |
| **Typesense only** | Simples, busca rápida, MCP Server direto | Sem queries avançadas, depende só do Typesense |
| **Qdrant only** | Especializado em vetores, performance | Adiciona nova dependência, MCP precisa mudar |

#### 4. Escopo de Processamento

| Opção | Prós | Contras |
|-------|------|---------|
| **Apenas 2025** | Todas têm summary (AI), ~30k records, rápido (~25 min) | Não cobre histórico |
| **Todas (300k)** | Cobertura completa | 270k sem summary, qualidade inferior, lento (~3h) |
| **2025 + backfill gradual** | Melhor dos dois | Complexidade adicional |

#### 5. Timing no Pipeline

| Opção | Prós | Contras |
|-------|------|---------|
| **Após enrich-themes** | Garante summary disponível, modular | Adiciona 2 jobs ao pipeline |
| **Durante enrich-themes** | Menos jobs | Acopla 2 responsabilidades |
| **Job separado noturno** | Não impacta pipeline diário | Lag maior |

### Decisão

**Estratégia escolhida**:

1. **Modelo**: `paraphrase-multilingual-mpnet-base-v2` (768 dims)
2. **Input**: `title + " " + summary` (com fallback para `content` se summary ausente)
3. **Storage**: PostgreSQL (pgvector) + Typesense
4. **Escopo**: **Apenas notícias de 2025** (~30k registros)
5. **Timing**: Job separado após `enrich-themes` no pipeline diário

**Workflow**:
```
scraper → PostgreSQL
    ↓
upload-cogfy → Cogfy API (gera summary)
    ↓
[wait 20 min]
    ↓
enrich-themes → PostgreSQL (themes + summary)
    ↓
[NOVO] generate-embeddings → PostgreSQL (embeddings de title + summary)
    ↓
[NOVO] sync-embeddings-to-typesense → Typesense (campo content_embedding)
```

### Justificativa

1. **Modelo paraphrase-multilingual-mpnet-base-v2**:
   - Já usado no projeto para classificação de temas (consistência)
   - Excelente performance em português (SBERT benchmark)
   - Modelo local (sem custos de API, sem latência de rede)
   - 768 dimensões é bom compromisso (qualidade vs performance)

2. **Input: title + summary**:
   - `summary` é AI-generated pelo Cogfy, mais limpo e semântico que `content` bruto
   - `content` tem muito ruído (HTML, listas, elementos estruturais)
   - Embeddings de summaries são mais representativos para busca semântica
   - Fallback para `content` garante compatibilidade se summary ausente

3. **Storage: PostgreSQL + Typesense**:
   - **PostgreSQL**: Permite queries avançadas (filtros + similaridade, analytics)
   - **Typesense**: Busca semântica rápida, já usado no MCP Server
   - Synergistic: PG para data platform, Typesense para aplicações
   - pgvector é maduro, bem suportado, performance excelente com HNSW

4. **Escopo: Apenas 2025**:
   - **Crítico**: Somente notícias de 2025 têm `summary` do Cogfy
   - Notícias anteriores (~270k) não têm summary → qualidade inferior
   - 30k registros de 2025 processam em ~25 minutos (aceitável)
   - Foco em dados recentes, mais relevantes para usuários
   - Possibilidade de expandir no futuro se necessário

5. **Timing: Job separado após enrich-themes**:
   - Garante que `summary` (do Cogfy) está disponível antes de gerar embeddings
   - Modular: pode falhar sem impactar resto do pipeline
   - Permite re-gerar embeddings sem re-scrape
   - 2 jobs separados (generate + sync) permite flexibilidade

### Consequências

**Positivas**:
- Busca semântica habilitada para notícias de 2025
- MCP Server do Typesense ganha capacidade semântica
- Embeddings armazenados no PostgreSQL para analytics
- Pipeline robusto com jobs modulares
- Testes automatizados garantem qualidade
- Secrets do Typesense já existem (sem setup adicional)

**Negativas**:
- Notícias anteriores a 2025 não terão embeddings
- Adiciona ~300 MB ao Cloud SQL (embeddings + índice HNSW)
- Docker image cresce ~620 MB (sentence-transformers + torch + modelo)
- Pipeline diário ganha ~5-10 minutos (geração + sync)
- Typesense schema update é destrutivo (requer recreate)

**Mitigações**:
- Scope limitado a 2025 mantém volume gerenciável
- Pre-download do modelo no Docker reduz tempo de cold start
- Testes locais com Docker (PostgreSQL + Typesense) antes de produção
- Backfill rápido (~25 min) permite re-processar se necessário
- Rollback simples (comentar jobs no workflow)

### Próximos Passos

1. Habilitar pgvector no Cloud SQL (Terraform)
2. Implementar `EmbeddingGenerator` class
3. Implementar `TypesenseSyncManager` class
4. Escrever testes automatizados (unit + integration)
5. Testar localmente com Docker
6. Adicionar 2 jobs ao workflow GitHub Actions
7. Atualizar schema do Typesense (adicionar campo `content_embedding`)
8. Backfill embeddings para 2025
9. Monitorar 1 semana
10. Sign-off

### Arquivos Afetados

**Novos**:
- `scripts/migrations/001_add_pgvector_extension.sql`
- `scripts/migrations/002_add_embedding_column.sql`
- `scripts/migrations/003_create_embedding_index.sql`
- `src/data_platform/jobs/embeddings/embedding_generator.py`
- `src/data_platform/jobs/embeddings/typesense_sync.py`
- `tests/unit/test_embedding_generator.py`
- `tests/unit/test_typesense_sync.py`
- `tests/integration/test_embedding_workflow.py`
- `scripts/backfill_embeddings.sh`

**Modificados**:
- `infra/terraform/cloud_sql.tf` (pgvector flag)
- `src/data_platform/models/news.py` (campos embedding)
- `src/data_platform/cli.py` (2 comandos)
- `pyproject.toml` (ML dependencies)
- `Dockerfile` (pre-download modelo)
- `.github/workflows/pipeline-steps.yaml` (2 jobs)
- `typesense/src/typesense_dgb/collection.py` (campo content_embedding)

---

## Template para Novas Decisões

```markdown
## ADR-XXX: [Título]

**Data**: YYYY-MM-DD
**Status**: Proposto | Aprovado | Deprecado | Substituído

### Contexto

[Descreva o contexto e o problema]

### Opções Consideradas

| Opção | Prós | Contras |
|-------|------|---------|
| **Opção 1** | ... | ... |
| **Opção 2** | ... | ... |

### Decisão

[Qual opção foi escolhida]

### Justificativa

[Por que esta opção foi escolhida]

### Consequências

[O que muda com esta decisão]
```

---

*Última atualização: 2024-12-24*
