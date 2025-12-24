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
