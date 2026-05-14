# Feature Registry

O Feature Registry (`feature_registry.yaml` na raiz do repositório) é a fonte de verdade para todas as features computadas do sistema.

---

## Propósito

- Documentar quais features existem e como são computadas
- Permitir reprocessamento seletivo quando um modelo muda (via campo `version`)
- Centralizar controle de versão das features
- Servir como referência para novos desenvolvedores

---

## Schema

```yaml
features:
  nome_da_feature:
    version: "1.0"          # Versão da feature (para reprocessamento)
    type: integer           # Tipo: integer, float, boolean, string, array, object
    description: "..."      # Descrição legível
    model: "local/python"   # Modelo/engine usado para computar
    compute: "feature-worker"  # Quem computa: feature-worker, enrichment-worker, thumbnail-worker, airflow-dag
```

---

## Features Atuais

### Features Locais (feature-worker)

| Feature | Tipo | Descrição |
|---------|------|-----------|
| `word_count` | integer | Contagem de palavras do conteúdo |
| `char_count` | integer | Contagem de caracteres |
| `paragraph_count` | integer | Contagem de parágrafos |
| `has_image` | boolean | Artigo possui imagem |
| `has_video` | boolean | Artigo possui vídeo |
| `publication_hour` | integer | Hora de publicação (0-23 UTC) |
| `publication_dow` | integer | Dia da semana (0=seg, 6=dom) |
| `readability_flesch` | float | Flesch reading ease (pt-BR) |

### Features IA (enrichment-worker)

| Feature | Tipo | Descrição |
|---------|------|-----------|
| `sentiment` | object | Análise de sentimento `{score, label}` |
| `entities` | array | Entidades nomeadas `[{text, type, count}]` |

### Features Thumbnail (thumbnail-worker)

| Feature | Tipo | Descrição |
|---------|------|-----------|
| `thumbnail_generated` | boolean | Thumbnail gerado com sucesso |
| `thumbnail_failed` | boolean | Falha na geração (vídeo inacessível) |

### Features Analíticas (airflow-dag)

| Feature | Tipo | Descrição |
|---------|------|-----------|
| `trending_score` | float | Score de trending (BigQuery) |
| `similar_articles` | array | IDs de artigos similares (pgvector cosine > 0.8) |
| `view_count` | integer | Total de visualizações (BigQuery pageviews) |
| `unique_sessions` | integer | Sessões únicas de visualização |

---

## Storage

Todas as features são armazenadas na tabela `news_features` do PostgreSQL:
- Coluna JSONB por artigo
- Referenciada por `unique_id` (FK para `news`)

---

## Como Adicionar uma Nova Feature

1. Adicionar entrada em `feature_registry.yaml` com version, type, description, model, compute
2. Implementar no compute source:
   - **feature-worker**: `src/data_platform/workers/feature_worker/features.py`
   - **airflow-dag**: criar job em `src/data_platform/jobs/` + DAG em `src/data_platform/dags/`
   - **enrichment-worker**: pipeline de enriquecimento (externo)
3. Testar localmente
4. Deploy (push to main)

---

## Versionamento

Quando um modelo muda (ex: trocar textstat por outro lib para readability):
1. Incrementar `version` no registry (ex: "1.0" → "2.0")
2. Reprocessar registros com versão antiga
3. O campo `version` permite queries como: "buscar artigos com readability_flesch v1.0 para reprocessar"

---

See also:
- [Feature Worker](../workers/README.md#feature-worker)
- [DAGs](../dags/README.md)
