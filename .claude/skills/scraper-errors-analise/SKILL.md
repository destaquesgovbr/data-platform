---
name: scraper-errors-analise
description: Analisa os erros dos scrapers nas últimas N execuções do workflow "Main News Processing Pipeline" e gera relatórios detalhados agrupados por URL e tipo de erro.
allowed-tools: Bash, Read, Write
---

# Análise de Erros dos Scrapers

Analisa os logs de erro dos jobs "News Scraper" e "EBC News Scraper" do workflow "Main News Processing Pipeline" e gera relatórios detalhados.

## Passo 1: Configurar Análise

Definir parâmetros da análise:
- **Número de execuções:** Padrão 20 (últimas 20 execuções do workflow)
- **Workflow ID:** 218846661 (Main News Processing Pipeline)
- **Jobs analisados:** "News Scraper" e "EBC News Scraper"

## Passo 2: Coletar Logs

Execute o script de coleta de logs:

```bash
cd /home/cesarv/projects/data-platform
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 20
```

Este script:
1. Lista as últimas N execuções do workflow via `gh run list`
2. Para cada execução, baixa os logs completos via `gh run view --log`
3. Extrai apenas as linhas com "ERROR" dos jobs relevantes
4. Salva em `/tmp/scraper_errors_raw.txt`

## Passo 3: Analisar Erros

Execute o script de análise:

```bash
python3 scripts/scraper_errors_analysis/analyze_errors.py
```

Este script:
1. Lê o arquivo de erros brutos
2. Identifica URLs com erro usando regex
3. Extrai o tipo de erro completo (ex: "403 Client Error: Forbidden")
4. Agrupa erros por URL
5. Gera estatísticas e relatórios

## Passo 4: Gerar Relatórios

O script gera 3 arquivos:

### 1. Relatório Executivo (`scraper_errors_executive_summary.md`)
- Resumo dos principais problemas
- URLs com 100% de falha
- Recomendações priorizadas

### 2. Relatório Detalhado (`scraper_errors_detailed.md`)
- Lista completa de todas as URLs com erro
- Tipos de erro específicos para cada URL
- Estatísticas por código HTTP

### 3. Dados JSON (`scraper_errors_data.json`)
- Dados estruturados para análises adicionais
- Pode ser usado para dashboards ou alertas

## Passo 5: Apresentar Resultados

Formato do relatório executivo:

```markdown
## 📊 Resumo Executivo

- Total de erros: N
- URLs únicas com problemas: N
- Taxa de falha crítica: X%

## 🔴 Principais Problemas

### URLs com Falhas Sistemáticas (100% de falha)
1. URL - Órgão (Código HTTP) → N/N falhas
2. ...

### Distribuição por Código HTTP
| Código | Descrição | Ocorrências | % |
|--------|-----------|-------------|---|
| 403 | Forbidden (bloqueio anti-bot) | N | X% |
| 404 | Not Found (URL obsoleta) | N | X% |
| 502 | Bad Gateway (servidor offline) | N | X% |

## 🔧 Recomendações
...
```

## Uso da Skill

### Análise Padrão (20 execuções):
```bash
/scraper-errors-analise
```

### Análise Customizada (50 execuções):
```bash
/scraper-errors-analise --runs 50
```

### Análise com Filtro de Data:
```bash
/scraper-errors-analise --runs 30 --since "2026-02-01"
```

## Interpretação dos Resultados

### Códigos HTTP Comuns

- **403 Forbidden**: WAF ou proteção anti-bot bloqueando o scraper
  - **Ação**: Implementar User-Agent rotation, delays entre requisições

- **404 Not Found**: URL obsoleta ou estrutura do site mudou
  - **Ação**: Validar URL manualmente, buscar nova URL do órgão

- **500/502/503**: Erro do servidor ou sistema fora do ar
  - **Ação**: Retry com backoff exponencial, verificar se site está online

- **Timeout**: Requisição demorou mais que 20s
  - **Ação**: Aumentar timeout ou implementar streaming

### URLs com 100% de Falha

URLs que falham em TODAS as execuções analisadas devem ser:
1. Desativadas temporariamente (`active: false` no arquivo de agências)
2. Investigadas individualmente (criar issue específica)
3. Validadas manualmente (acessar URL no navegador)

## Arquivos de Saída

Todos os relatórios são salvos em `/tmp/`:
- `/tmp/scraper_errors_raw.txt` - Logs brutos extraídos
- `/tmp/scraper_errors_executive_summary.md` - Sumário executivo
- `/tmp/scraper_errors_detailed.md` - Relatório completo
- `/tmp/scraper_errors_data.json` - Dados estruturados

## Integração com Issues

Após gerar o relatório, você pode:

1. **Criar issue para URLs específicas:**
   ```bash
   gh issue create --repo destaquesgovbr/data-platform \
     --title "Fix scraper: URL gov.br/abc retornando 403" \
     --body "URL falhando em 20/20 execuções..."
   ```

2. **Atualizar issues existentes:**
   - data-platform#58: Corrigir URLs Quebradas (403, 404)
   - data-platform#60: Corrigir Scraper EBC (502)

## Manutenção

### Atualizar Workflow ID
Se o workflow ID mudar, edite o script `collect_logs.py`:
```python
WORKFLOW_ID = "218846661"  # Atualizar se necessário
```

### Adicionar Novos Padrões de Erro
Para capturar novos formatos de erro, edite `analyze_errors.py`:
```python
ERROR_PATTERNS = [
    r'HTTP error when accessing (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
    r'Request failed for (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
    # Adicionar novos padrões aqui
]
```