#!/usr/bin/env python3
"""
Coleta logs de erro das execuções do workflow "Main News Processing Pipeline".

Uso:
    python3 collect_logs.py --runs 20
    python3 collect_logs.py --runs 50 --since "2026-02-01"
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = "destaquesgovbr/data-platform"
WORKFLOW_ID = "218846661"  # Main News Processing Pipeline
OUTPUT_FILE = "/tmp/scraper_errors_raw.txt"


def run_command(cmd, description=None):
    """Executa comando shell e retorna output."""
    if description:
        print(f"  {description}...")
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True
    )
    if result.returncode != 0 and description:
        print(f"    ⚠️  Warning: {description} failed")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(
        description="Coleta logs de erro dos scrapers"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=20,
        help="Número de execuções do workflow para analisar (padrão: 20)"
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Data inicial para filtrar execuções (formato: YYYY-MM-DD)"
    )
    args = parser.parse_args()

    print(f"🔍 Coletando logs de {args.runs} execuções do workflow...")
    print()

    # Listar últimas execuções
    cmd = f'gh run list --repo {REPO} --workflow={WORKFLOW_ID} --limit {args.runs} --json databaseId,status,conclusion,createdAt'
    output = run_command(cmd, f"Listando últimas {args.runs} execuções")

    if not output:
        print("❌ Erro ao listar execuções do workflow")
        sys.exit(1)

    runs = json.loads(output)
    run_ids = [run['databaseId'] for run in runs]

    print(f"✅ Encontradas {len(run_ids)} execuções")
    print()

    # Coletar logs de cada execução
    all_errors = []

    with open(OUTPUT_FILE, 'w') as f:
        for i, run_id in enumerate(run_ids, 1):
            print(f"[{i:2d}/{len(run_ids)}] Processando run {run_id}...")

            # Baixar logs da execução
            cmd = f'gh run view {run_id} --repo {REPO} --log 2>/dev/null'
            logs = run_command(cmd)

            if not logs:
                print(f"    ⚠️  Sem logs disponíveis")
                continue

            # Extrair apenas linhas com ERROR dos jobs relevantes
            error_count = 0
            for line in logs.splitlines():
                if 'ERROR' in line and ('News Scraper' in line or 'EBC News Scraper' in line):
                    f.write(line + '\n')
                    error_count += 1

            if error_count > 0:
                print(f"    ✅ {error_count} erros encontrados")
            else:
                print(f"    ℹ️  Nenhum erro nesta execução")

    print()
    print(f"✅ Coleta concluída!")
    print(f"📄 Logs salvos em: {OUTPUT_FILE}")
    print()

    # Contar total de linhas
    with open(OUTPUT_FILE, 'r') as f:
        total_lines = len(f.readlines())

    print(f"📊 Total de linhas com ERROR: {total_lines}")


if __name__ == "__main__":
    main()