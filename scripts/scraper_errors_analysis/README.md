# Scraper Errors Analysis

Scripts para análise de erros dos scrapers do workflow "Main News Processing Pipeline".

## Visão Geral

Este conjunto de scripts coleta logs de execuções do workflow, identifica erros, e gera relatórios detalhados agrupados por URL e tipo de erro.

## Requisitos

- GitHub CLI (`gh`) instalado e autenticado
- Python 3.7+
- Acesso ao repositório `destaquesgovbr/data-platform`

## Uso Rápido

```bash
# 1. Coletar logs das últimas 20 execuções
cd /home/cesarv/projects/data-platform
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 20

# 2. Analisar erros e gerar relatórios
python3 scripts/scraper_errors_analysis/analyze_errors.py
```

## Scripts

### 1. `collect_logs.py`

Coleta logs de erro das execuções do workflow.

**Uso:**
```bash
# Análise padrão (20 execuções)
python3 collect_logs.py

# Análise customizada
python3 collect_logs.py --runs 50

# Com filtro de data
python3 collect_logs.py --runs 30 --since "2026-02-01"
```

**Opções:**
- `--runs N`: Número de execuções para analisar (padrão: 20)
- `--since DATE`: Data inicial (formato: YYYY-MM-DD)

**Saída:**
- `/tmp/scraper_errors_raw.txt`: Logs brutos com linhas de ERROR

### 2. `analyze_errors.py`

Analisa logs coletados e gera relatórios.

**Uso:**
```bash
# Análise padrão
python3 analyze_errors.py

# Análise de arquivo customizado
python3 analyze_errors.py --input /path/to/logs.txt
```

**Opções:**
- `--input FILE`: Arquivo de entrada (padrão: /tmp/scraper_errors_raw.txt)

**Saída:**
- `/tmp/scraper_errors_executive_summary.md`: Sumário executivo
- `/tmp/scraper_errors_detailed.md`: Relatório completo
- `/tmp/scraper_errors_data.json`: Dados estruturados (JSON)

## Relatórios Gerados

### Sumário Executivo

Contém:
- Estatísticas gerais (total de erros, URLs únicas)
- Distribuição por código HTTP
- Top 15 URLs com mais erros
- Recomendações priorizadas

### Relatório Detalhado

Contém:
- Lista completa de todas as URLs com erro
- Tipos de erro específicos para cada URL
- Estatísticas por código HTTP e tipo de erro

### Dados JSON

Formato estruturado para:
- Integração com dashboards
- Análises adicionais
- Alertas automatizados

Exemplo:
```json
{
  "total_errors": 467,
  "total_urls": 101,
  "error_codes": {
    "403": 220,
    "404": 60,
    "502": 20
  },
  "urls": [
    {
      "url": "https://www.gov.br/abc/pt-br/assuntos/noticias",
      "total_errors": 20,
      "errors": {
        "403 Client Error: Forbidden": 20
      }
    }
  ]
}
```

## Interpretação dos Resultados

### Códigos HTTP

| Código | Descrição | Ação Recomendada |
|--------|-----------|------------------|
| 403 | Forbidden (bloqueio anti-bot) | Implementar User-Agent rotation, delays |
| 404 | Not Found (URL obsoleta) | Validar URL, buscar nova URL do órgão |
| 500 | Internal Server Error | Retry com backoff, verificar site |
| 502 | Bad Gateway (servidor offline) | Verificar se site está online |
| 503 | Service Unavailable | Aguardar recuperação, retry |

### URLs Críticas

URLs com **100% de falha** (ex: 20/20) devem ser:
1. Desativadas temporariamente (`active: false`)
2. Investigadas individualmente
3. Validadas manualmente no navegador

## Exemplos de Uso

### Análise de Rotina (Semanal)

```bash
# Coletar e analisar últimas 20 execuções
cd /home/cesarv/projects/data-platform
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 20
python3 scripts/scraper_errors_analysis/analyze_errors.py

# Visualizar sumário
cat /tmp/scraper_errors_executive_summary.md
```

### Análise Profunda (Mensal)

```bash
# Analisar últimas 50 execuções
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 50
python3 scripts/scraper_errors_analysis/analyze_errors.py

# Gerar issues para URLs críticas
# (ver seção "Integração com Issues" abaixo)
```

### Análise Específica

```bash
# Analisar período específico
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 30 --since "2026-02-01"
python3 scripts/scraper_errors_analysis/analyze_errors.py
```

## Integração com Issues

Após gerar relatórios, você pode criar issues para URLs específicas:

```bash
# Criar issue para URL crítica
gh issue create --repo destaquesgovbr/data-platform \
  --title "Fix scraper: URL gov.br/abc retornando 403 Forbidden" \
  --label "bug" \
  --label "area:scraper" \
  --label "priority:high" \
  --body "URL falhando em 20/20 execuções (100%).

**Erro:** 403 Client Error: Forbidden
**URL:** https://www.gov.br/abc/pt-br/assuntos/noticias

**Ação:**
1. Validar URL manualmente
2. Implementar User-Agent rotation
3. Adicionar delays entre requisições

**Relatório:** Ver /tmp/scraper_errors_executive_summary.md"
```

## Manutenção

### Atualizar Workflow ID

Se o workflow ID mudar:

```python
# Em collect_logs.py
WORKFLOW_ID = "218846661"  # Atualizar aqui
```

### Adicionar Novos Padrões de Erro

Para capturar novos formatos de erro:

```python
# Em analyze_errors.py
ERROR_PATTERNS = [
    r'HTTP error when accessing (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
    r'Request failed for (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
    # Adicionar novos padrões aqui
    r'Novo padrão: (url) - (erro)',
]
```

## Troubleshooting

### Erro: "Arquivo não encontrado"

```bash
# Certifique-se de executar collect_logs.py primeiro
python3 scripts/scraper_errors_analysis/collect_logs.py --runs 20
```

### Erro: "gh: command not found"

```bash
# Instalar GitHub CLI
# https://cli.github.com/
```

### Erro: "Permission denied"

```bash
# Tornar scripts executáveis
chmod +x scripts/scraper_errors_analysis/*.py
```

## Skill do Claude Code

Para usar com Claude Code:

```bash
/scraper-errors-analise
```

Documentação completa da skill: `.claude/skills/scraper-errors-analise/SKILL.md`