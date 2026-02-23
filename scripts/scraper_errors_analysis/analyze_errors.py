#!/usr/bin/env python3
"""
Analisa erros dos scrapers e gera relatórios detalhados.

Uso:
    python3 analyze_errors.py
    python3 analyze_errors.py --input /path/to/logs.txt
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Padrões de erro
ERROR_PATTERNS = [
    # HTTP error when accessing URL: ERROR_TYPE
    r'HTTP error when accessing (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
    # Request failed for URL: ERROR_TYPE
    r'Request failed for (https?://[^\s:]+):\s+(.+?)(?:\s+for url:|$)',
]

# Mapeamento de códigos HTTP
HTTP_CODE_DESCRIPTIONS = {
    '403': 'Forbidden (bloqueio anti-bot)',
    '404': 'Not Found (URL inexistente)',
    '500': 'Internal Server Error',
    '502': 'Bad Gateway (servidor offline)',
    '503': 'Service Unavailable',
    '504': 'Gateway Timeout',
}


def extract_errors(input_file):
    """Extrai URLs e tipos de erro do arquivo de logs."""
    url_errors = defaultdict(lambda: defaultdict(int))
    total_http_errors = 0

    with open(input_file, 'r') as f:
        for line in f:
            for pattern in ERROR_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    url, error_type = match.groups()
                    url_base = url.split('?')[0]
                    error_type = error_type.strip()
                    url_errors[url_base][error_type] += 1
                    total_http_errors += 1
                    break

    return url_errors, total_http_errors


def generate_executive_summary(url_stats, error_codes, total_errors):
    """Gera relatório executivo."""
    lines = []
    lines.append("# Relatório Executivo: Análise de Erros dos Scrapers")
    lines.append("")
    lines.append(f"**Período:** Últimas execuções do workflow \"Main News Processing Pipeline\"")
    lines.append(f"**Data de geração:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append(f"**Repositório:** destaquesgovbr/data-platform")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Resumo Executivo")
    lines.append("")
    lines.append(f"- **Total de erros HTTP registrados:** {total_errors}")
    lines.append(f"- **URLs únicas com problemas:** {len(url_stats)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Distribuição por código HTTP
    lines.append("## 📈 Distribuição por Código HTTP")
    lines.append("")
    lines.append("| Código | Descrição | Ocorrências | % |")
    lines.append("|--------|-----------|-------------|---|")
    for code, count in sorted(error_codes.items(), key=lambda x: -x[1]):
        pct = (count / total_errors * 100) if total_errors > 0 else 0
        desc = HTTP_CODE_DESCRIPTIONS.get(code, 'Erro do servidor')
        lines.append(f"| {code} | {desc} | {count} | {pct:.1f}% |")
    lines.append("")

    # Top 15 URLs com mais erros
    lines.append("## 🔴 Top 15 URLs com Mais Erros")
    lines.append("")
    lines.append("| # | URL | Total Erros | Principal Erro |")
    lines.append("|---|-----|-------------|----------------|")
    for i, (url, errors, total) in enumerate(url_stats[:15], 1):
        parsed = urlparse(url)
        display_url = f"{parsed.netloc.replace('www.', '')}{parsed.path[:50]}"
        if len(parsed.path) > 50:
            display_url += "..."

        # Erro mais comum
        main_error = sorted(errors.items(), key=lambda x: -x[1])[0][0]
        code_match = re.match(r'(\d+)', main_error)
        code = code_match.group(1) if code_match else "N/A"

        lines.append(f"| {i} | {display_url} | {total} | HTTP {code} |")
    lines.append("")

    # Recomendações
    lines.append("## 🔧 Recomendações")
    lines.append("")

    # Identificar URLs com muitas falhas
    critical_urls = [stats for stats in url_stats if stats[2] >= 20]

    if critical_urls:
        lines.append("### Prioridade 0 - Imediato")
        lines.append("")
        lines.append(f"**{len(critical_urls)} URLs com falhas críticas (≥20 erros):**")
        lines.append("")
        for url, errors, total in critical_urls[:10]:
            main_error = sorted(errors.items(), key=lambda x: -x[1])[0][0]
            code_match = re.match(r'(\d+)', main_error)
            code = code_match.group(1) if code_match else "???"
            parsed = urlparse(url)
            display = f"{parsed.netloc.replace('www.', '')}{parsed.path[:60]}"
            lines.append(f"- [{code}] {display}")

        lines.append("")
        lines.append("**Ações recomendadas:**")
        lines.append("1. Desativar temporariamente estas URLs (`active: false`)")
        lines.append("2. Criar issues específicas para investigação")
        lines.append("3. Validar manualmente cada URL")
        lines.append("")

    # Recomendações por código
    forbidden_count = error_codes.get('403', 0)
    not_found_count = error_codes.get('404', 0)

    if forbidden_count > 0:
        pct = (forbidden_count / total_errors * 100)
        lines.append(f"### 403 Forbidden ({forbidden_count} erros, {pct:.1f}%)")
        lines.append("**Causa:** Proteção anti-bot ou WAF bloqueando o scraper")
        lines.append("**Solução:**")
        lines.append("- Implementar User-Agent rotation")
        lines.append("- Adicionar delays aleatórios entre requisições")
        lines.append("- Usar proxies rotativos")
        lines.append("")

    if not_found_count > 0:
        pct = (not_found_count / total_errors * 100)
        lines.append(f"### 404 Not Found ({not_found_count} erros, {pct:.1f}%)")
        lines.append("**Causa:** URL obsoleta ou estrutura do site mudou")
        lines.append("**Solução:**")
        lines.append("- Validar URLs manualmente")
        lines.append("- Buscar nova URL dos órgãos")
        lines.append("- Atualizar configuração das agências")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Relatório completo:** `/tmp/scraper_errors_detailed.md`")
    lines.append("")

    return '\n'.join(lines)


def generate_detailed_report(url_stats, error_types_summary, error_codes, total_errors):
    """Gera relatório detalhado."""
    lines = []
    lines.append("# Relatório Detalhado de Erros dos Scrapers")
    lines.append("")
    lines.append(f"**Data de geração:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append(f"**Total de erros HTTP:** {total_errors}")
    lines.append(f"**URLs únicas:** {len(url_stats)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Resumo por código HTTP
    lines.append("## Resumo por Código HTTP")
    lines.append("")
    lines.append("| Código | Descrição | Ocorrências | % |")
    lines.append("|--------|-----------|-------------|---|")
    for code, count in sorted(error_codes.items(), key=lambda x: -x[1]):
        pct = (count / total_errors * 100) if total_errors > 0 else 0
        desc = HTTP_CODE_DESCRIPTIONS.get(code, 'Erro do servidor')
        lines.append(f"| {code} | {desc} | {count} | {pct:.1f}% |")
    lines.append("")

    # Resumo por tipo de erro detalhado
    lines.append("## Resumo por Tipo de Erro Detalhado (Top 10)")
    lines.append("")
    lines.append("| Tipo de Erro Completo | Ocorrências | % |")
    lines.append("|-----------------------|-------------|---|")
    for error_type, count in sorted(error_types_summary.items(), key=lambda x: -x[1])[:10]:
        pct = (count / total_errors * 100) if total_errors > 0 else 0
        lines.append(f"| `{error_type}` | {count} | {pct:.1f}% |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detalhamento por URL
    lines.append("## Erros por URL")
    lines.append("")

    for i, (url, errors, total) in enumerate(url_stats, 1):
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')
        path = parsed.path

        lines.append(f"### {i}. {domain}{path}")
        lines.append("")
        lines.append(f"**URL Completa:** `{url}`")
        lines.append(f"**Total de ocorrências:** {total}")
        lines.append("")
        lines.append("| Tipo de Erro | Ocorrências |")
        lines.append("|--------------|-------------|")
        for error_type, count in sorted(errors.items(), key=lambda x: -x[1]):
            lines.append(f"| `{error_type}` | {count} |")
        lines.append("")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analisa erros dos scrapers")
    parser.add_argument(
        "--input",
        type=str,
        default="/tmp/scraper_errors_raw.txt",
        help="Arquivo de entrada com logs de erro (padrão: /tmp/scraper_errors_raw.txt)"
    )
    args = parser.parse_args()

    input_file = Path(args.input)
    if not input_file.exists():
        print(f"❌ Arquivo não encontrado: {input_file}")
        print("Execute primeiro: python3 collect_logs.py")
        return

    print("🔍 Analisando erros...")
    print()

    # Extrair erros
    url_errors, total_http_errors = extract_errors(input_file)

    if total_http_errors == 0:
        print("ℹ️  Nenhum erro HTTP encontrado nos logs")
        return

    # Calcular estatísticas
    url_stats = []
    error_types_summary = defaultdict(int)
    error_codes = defaultdict(int)

    for url, errors in url_errors.items():
        total = sum(errors.values())
        url_stats.append((url, errors, total))

        for error_detail, count in errors.items():
            error_types_summary[error_detail] += count
            code_match = re.match(r'(\d+)', error_detail)
            if code_match:
                error_codes[code_match.group(1)] += count

    url_stats.sort(key=lambda x: -x[2])

    # Gerar relatórios
    print("📝 Gerando relatórios...")

    executive = generate_executive_summary(url_stats, error_codes, total_http_errors)
    with open('/tmp/scraper_errors_executive_summary.md', 'w') as f:
        f.write(executive)

    detailed = generate_detailed_report(url_stats, error_types_summary, error_codes, total_http_errors)
    with open('/tmp/scraper_errors_detailed.md', 'w') as f:
        f.write(detailed)

    # Salvar dados em JSON
    json_data = {
        'total_errors': total_http_errors,
        'total_urls': len(url_stats),
        'error_codes': dict(error_codes),
        'urls': [
            {
                'url': url,
                'total_errors': total,
                'errors': dict(errors)
            }
            for url, errors, total in url_stats
        ]
    }
    with open('/tmp/scraper_errors_data.json', 'w') as f:
        json.dump(json_data, f, indent=2)

    print()
    print("✅ Análise concluída!")
    print()
    print("📄 Arquivos gerados:")
    print("  - /tmp/scraper_errors_executive_summary.md (Sumário executivo)")
    print("  - /tmp/scraper_errors_detailed.md (Relatório completo)")
    print("  - /tmp/scraper_errors_data.json (Dados estruturados)")
    print()

    # Estatísticas rápidas
    print("## 📊 Estatísticas Rápidas")
    print()
    print(f"Total de erros HTTP: {total_http_errors}")
    print(f"URLs únicas: {len(url_stats)}")
    print()

    print("Top 10 URLs:")
    for i, (url, errors, total) in enumerate(url_stats[:10], 1):
        parsed = urlparse(url)
        display = f"{parsed.netloc.replace('www.', '')}{parsed.path[:50]}"
        main_error = sorted(errors.items(), key=lambda x: -x[1])[0][0]
        code_match = re.match(r'(\d+)', main_error)
        code = code_match.group(1) if code_match else "???"
        print(f"  {i:2d}. [HTTP {code}] {display:55s} → {total:3d} erros")


if __name__ == "__main__":
    main()