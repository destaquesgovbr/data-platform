#!/usr/bin/env python3
"""
Migração Offline de Embeddings: mpnet-768d → BGE-M3-1024d

Script otimizado para GPU (L4) que processa dumps do PostgreSQL,
gera embeddings com BGE-M3 e prepara dados para bulk upload.

Uso:
    # 1. Gerar embeddings
    python migrate_to_bge_m3.py generate \
        --input artigos_para_migrar.parquet \
        --output embeddings_bge_m3.parquet \
        --batch-size 128

    # 2. Upload para PostgreSQL
    python migrate_to_bge_m3.py upload \
        --input embeddings_bge_m3.parquet \
        --database-url $DATABASE_URL

    # 3. Pipeline completo
    python migrate_to_bge_m3.py full \
        --input artigos_para_migrar.parquet \
        --database-url $DATABASE_URL

Autor: Luis Felipe de Moraes
Data: 2026-06-16
Relacionado: data-platform#175, data-science#1
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import psycopg2
import torch
from sentence_transformers import SentenceTransformer
from tqdm.auto import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("migration.log"),
    ],
)
logger = logging.getLogger(__name__)


class BGE_M3_Migrator:
    """Migrador de embeddings com suporte a GPU e checkpoints."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        batch_size: int = 128,
        device: Optional[str] = None,
    ):
        """
        Inicializa o migrador.

        Args:
            model_name: Nome do modelo no HuggingFace
            batch_size: Tamanho do batch para inferência
            device: Device PyTorch ('cuda', 'cpu', ou None para auto-detect)
        """
        # Auto-detect device
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device

        logger.info(f"Initializing migrator...")
        logger.info(f"  Model: {model_name}")
        logger.info(f"  Device: {device}")
        logger.info(f"  Batch size: {batch_size}")

        if device == "cuda":
            logger.info(f"  GPU: {torch.cuda.get_device_name(0)}")
            logger.info(
                f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB"
            )

        # Load model
        logger.info(f"Loading model {model_name}...")
        start = time.time()
        self.model = SentenceTransformer(model_name, device=device)
        elapsed = time.time() - start
        logger.info(f"Model loaded in {elapsed:.1f}s")
        logger.info(f"  Embedding dimension: {self.model.get_sentence_embedding_dimension()}")

    def prepare_text(self, row: pd.Series) -> str:
        """
        Prepara texto para embedding (mesmo formato do embeddings-api).

        Lógica:
        1. Se tem summary: title + summary
        2. Senão, se tem content: title + primeiros 500 chars
        3. Senão: só title

        Args:
            row: Linha do DataFrame com colunas title, summary, content

        Returns:
            Texto preparado para embedding
        """
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip() if pd.notna(row.get("summary")) else ""
        content = str(row.get("content") or "").strip() if pd.notna(row.get("content")) else ""

        if summary:
            return f"{title}. {summary}" if title else summary
        elif content:
            content_preview = content[:500]
            return f"{title}. {content_preview}" if title else content_preview
        else:
            return title if title else ""

    def process_batch(self, articles: pd.DataFrame) -> np.ndarray:
        """
        Gera embeddings para um batch de artigos.

        Args:
            articles: DataFrame com artigos

        Returns:
            Array numpy (batch_size, 1024) com embeddings
        """
        texts = [self.prepare_text(row) for _, row in articles.iterrows()]

        # GPU inference
        with torch.no_grad():
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=False,  # BGE-M3 não precisa normalização
            )

        return embeddings

    def migrate_from_dump(
        self,
        dump_path: str,
        output_path: str,
        checkpoint_every: int = 10000,
        resume_from: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Processa dump e gera embeddings.

        Args:
            dump_path: Caminho para arquivo de input (parquet/csv)
            output_path: Caminho para salvar embeddings
            checkpoint_every: Salvar checkpoint a cada N artigos
            resume_from: Caminho de checkpoint para retomar

        Returns:
            DataFrame com id, unique_id, embedding
        """
        logger.info(f"Starting migration...")
        logger.info(f"  Input: {dump_path}")
        logger.info(f"  Output: {output_path}")

        # Load dump
        logger.info(f"Reading dump from {dump_path}...")
        if dump_path.endswith(".parquet"):
            df = pd.read_parquet(dump_path)
        elif dump_path.endswith(".csv"):
            df = pd.read_csv(dump_path)
        else:
            raise ValueError("Input must be .parquet or .csv")

        total = len(df)
        logger.info(f"Total articles to process: {total:,}")

        # Check required columns
        required_cols = ["id", "unique_id", "title"]
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Resume from checkpoint
        start_idx = 0
        results = []
        if resume_from and Path(resume_from).exists():
            logger.info(f"Resuming from checkpoint: {resume_from}")
            checkpoint_df = pd.read_parquet(resume_from)
            results = checkpoint_df.to_dict("records")
            start_idx = len(results)
            logger.info(f"Resuming from article {start_idx:,}")

        # Process in batches
        processed = start_idx
        errors = 0
        start_time = time.time()

        with tqdm(
            total=total,
            initial=start_idx,
            desc="Generating embeddings",
            unit="articles",
        ) as pbar:
            for i in range(start_idx, total, self.batch_size):
                batch = df.iloc[i : i + self.batch_size]

                try:
                    embeddings = self.process_batch(batch)

                    for (_, row), embedding in zip(batch.iterrows(), embeddings):
                        results.append(
                            {
                                "id": int(row["id"]),
                                "unique_id": str(row["unique_id"]),
                                "embedding": embedding.tolist(),
                            }
                        )

                    processed += len(batch)
                    pbar.update(len(batch))

                    # Checkpoint
                    if processed % checkpoint_every == 0:
                        self._save_checkpoint(results, output_path, processed)
                        elapsed = time.time() - start_time
                        rate = processed / elapsed
                        eta = (total - processed) / rate if rate > 0 else 0
                        logger.info(
                            f"Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) | "
                            f"Rate: {rate:.0f} articles/s | ETA: {eta/3600:.1f}h"
                        )

                except Exception as e:
                    logger.error(f"Error processing batch at index {i}: {e}")
                    errors += 1
                    if errors > 10:
                        logger.error("Too many errors, aborting...")
                        raise

        # Final save
        elapsed = time.time() - start_time
        logger.info(f"Migration complete!")
        logger.info(f"  Processed: {processed:,} articles")
        logger.info(f"  Errors: {errors}")
        logger.info(f"  Time: {elapsed/3600:.2f}h")
        logger.info(f"  Rate: {processed/elapsed:.0f} articles/s")
        logger.info(f"Saving final results to {output_path}...")

        results_df = pd.DataFrame(results)
        results_df.to_parquet(output_path, index=False)

        # Save metadata
        metadata = {
            "model": self.model_name,
            "dimension": 1024,
            "total_articles": len(results_df),
            "errors": errors,
            "elapsed_seconds": elapsed,
            "timestamp": datetime.now().isoformat(),
        }
        metadata_path = output_path.replace(".parquet", "_metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Done! Results saved to {output_path}")
        return results_df

    def _save_checkpoint(self, results: List[dict], output_path: str, batch_num: int):
        """Salva checkpoint intermediário."""
        checkpoint_path = output_path.replace(
            ".parquet", f"_checkpoint_{batch_num}.parquet"
        )
        pd.DataFrame(results).to_parquet(checkpoint_path, index=False)
        logger.debug(f"Checkpoint saved: {checkpoint_path}")


def bulk_upload_to_postgres(
    embeddings_path: str,
    database_url: str,
    batch_size: int = 1000,
    dry_run: bool = False,
):
    """
    Faz bulk upload de embeddings para PostgreSQL.

    Args:
        embeddings_path: Caminho do arquivo com embeddings
        database_url: Connection string do PostgreSQL
        batch_size: Tamanho do batch para updates
        dry_run: Se True, não executa updates (teste)
    """
    logger.info(f"Starting bulk upload to PostgreSQL...")
    logger.info(f"  Input: {embeddings_path}")
    logger.info(f"  Batch size: {batch_size}")
    logger.info(f"  Dry run: {dry_run}")

    # Load embeddings
    logger.info("Loading embeddings...")
    embeddings_df = pd.read_parquet(embeddings_path)
    total = len(embeddings_df)
    logger.info(f"Total embeddings to upload: {total:,}")

    if dry_run:
        logger.info("DRY RUN: Skipping database connection")
        logger.info(f"Would upload {total:,} embeddings")
        return

    # Connect to PostgreSQL
    logger.info("Connecting to PostgreSQL...")
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()

    # Upload in batches
    uploaded = 0
    errors = 0
    start_time = time.time()

    with tqdm(total=total, desc="Uploading", unit="embeddings") as pbar:
        for i in range(0, total, batch_size):
            batch = embeddings_df.iloc[i : i + batch_size]

            try:
                for _, row in batch.iterrows():
                    cursor.execute(
                        """
                        UPDATE news
                        SET content_embedding = %s::vector,
                            embedding_model_version = 'bge-m3',
                            embedding_generated_at = NOW()
                        WHERE id = %s
                        """,
                        (row["embedding"], row["id"]),
                    )

                conn.commit()
                uploaded += len(batch)
                pbar.update(len(batch))

            except Exception as e:
                logger.error(f"Error uploading batch at index {i}: {e}")
                conn.rollback()
                errors += 1
                if errors > 10:
                    logger.error("Too many errors, aborting...")
                    raise

    elapsed = time.time() - start_time

    cursor.close()
    conn.close()

    logger.info(f"Upload complete!")
    logger.info(f"  Uploaded: {uploaded:,} embeddings")
    logger.info(f"  Errors: {errors}")
    logger.info(f"  Time: {elapsed:.1f}s")
    logger.info(f"  Rate: {uploaded/elapsed:.0f} updates/s")


def main():
    parser = argparse.ArgumentParser(
        description="Migração de embeddings mpnet → BGE-M3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Comando a executar")

    # Generate command
    generate_parser = subparsers.add_parser(
        "generate", help="Gerar embeddings a partir de dump"
    )
    generate_parser.add_argument(
        "--input", required=True, help="Arquivo de input (parquet/csv)"
    )
    generate_parser.add_argument(
        "--output", required=True, help="Arquivo de output (parquet)"
    )
    generate_parser.add_argument(
        "--batch-size", type=int, default=128, help="Batch size para GPU (default: 128)"
    )
    generate_parser.add_argument(
        "--device", default=None, help="Device PyTorch (cuda/cpu, default: auto)"
    )
    generate_parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10000,
        help="Salvar checkpoint a cada N artigos (default: 10000)",
    )
    generate_parser.add_argument(
        "--resume-from", help="Retomar de checkpoint (caminho do checkpoint.parquet)"
    )

    # Upload command
    upload_parser = subparsers.add_parser(
        "upload", help="Upload embeddings para PostgreSQL"
    )
    upload_parser.add_argument(
        "--input", required=True, help="Arquivo com embeddings (parquet)"
    )
    upload_parser.add_argument(
        "--database-url", required=True, help="PostgreSQL connection string"
    )
    upload_parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size para updates (default: 1000)",
    )
    upload_parser.add_argument(
        "--dry-run", action="store_true", help="Modo teste (não executa updates)"
    )

    # Full pipeline command
    full_parser = subparsers.add_parser(
        "full", help="Pipeline completo (generate + upload)"
    )
    full_parser.add_argument(
        "--input", required=True, help="Arquivo de input (parquet/csv)"
    )
    full_parser.add_argument(
        "--database-url", required=True, help="PostgreSQL connection string"
    )
    full_parser.add_argument(
        "--batch-size", type=int, default=128, help="Batch size para GPU"
    )
    full_parser.add_argument("--device", default=None, help="Device PyTorch")
    full_parser.add_argument(
        "--keep-embeddings",
        action="store_true",
        help="Manter arquivo de embeddings após upload",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "generate":
            migrator = BGE_M3_Migrator(
                batch_size=args.batch_size, device=args.device
            )
            migrator.migrate_from_dump(
                dump_path=args.input,
                output_path=args.output,
                checkpoint_every=args.checkpoint_every,
                resume_from=args.resume_from,
            )

        elif args.command == "upload":
            bulk_upload_to_postgres(
                embeddings_path=args.input,
                database_url=args.database_url,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )

        elif args.command == "full":
            # Generate
            embeddings_path = args.input.replace(".parquet", "_embeddings.parquet")
            migrator = BGE_M3_Migrator(
                batch_size=args.batch_size, device=args.device
            )
            migrator.migrate_from_dump(
                dump_path=args.input, output_path=embeddings_path
            )

            # Upload
            bulk_upload_to_postgres(
                embeddings_path=embeddings_path,
                database_url=args.database_url,
            )

            # Cleanup
            if not args.keep_embeddings:
                logger.info(f"Removing temporary file: {embeddings_path}")
                Path(embeddings_path).unlink()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
