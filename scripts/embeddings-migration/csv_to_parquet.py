#!/usr/bin/env python3
"""
Converte CSV exportado do PostgreSQL para Parquet (formato mais eficiente).

Uso:
    python csv_to_parquet.py artigos_para_migrar.csv

Saída:
    artigos_para_migrar.parquet
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(description="Converte CSV para Parquet")
    parser.add_argument("input_csv", help="Arquivo CSV de input")
    parser.add_argument(
        "-o",
        "--output",
        help="Arquivo Parquet de output (default: input com extensão .parquet)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        help="Processar apenas N primeiras linhas (para teste)",
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    output_path = (
        Path(args.output) if args.output else input_path.with_suffix(".parquet")
    )

    print(f"Reading CSV: {input_path}")
    if args.sample:
        df = pd.read_csv(input_path, nrows=args.sample)
        print(f"  Loaded sample: {len(df):,} rows")
    else:
        df = pd.read_csv(input_path)
        print(f"  Loaded: {len(df):,} rows")

    print(f"  Columns: {list(df.columns)}")
    print(f"  Memory: {df.memory_usage(deep=True).sum() / 1e6:.1f} MB")

    print(f"Converting to Parquet: {output_path}")
    df.to_parquet(output_path, index=False)

    # Verify
    output_size = output_path.stat().st_size / 1e6
    compression_ratio = (
        input_path.stat().st_size / output_path.stat().st_size if output_path.stat().st_size > 0 else 0
    )

    print(f"Done!")
    print(f"  Output size: {output_size:.1f} MB")
    print(f"  Compression ratio: {compression_ratio:.1f}x")
    print(f"  Saved to: {output_path}")


if __name__ == "__main__":
    main()
