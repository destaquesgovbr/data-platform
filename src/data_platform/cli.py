"""
Unified CLI for the DestaquesGovBr data platform.

Commands:
- sync-hf: Sync PostgreSQL data to HuggingFace
- migrate: Migrate data from HuggingFace to PostgreSQL
- sync-typesense: Sync news from PostgreSQL to Typesense
- typesense-delete: Delete a Typesense collection
- typesense-list: List all Typesense collections

Note: Scraping commands moved to standalone scraper repo.
Note: Enrichment commands removed — now handled by Airflow DAG enrich_news_llm (data-science repo).
"""
import logging
from typing import Optional

import typer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = typer.Typer(
    name="data-platform",
    help="Data platform for DestaquesGovBr - storage and indexing"
)


@app.command("sync-hf")
def sync_hf() -> None:
    """Sync PostgreSQL data to HuggingFace."""
    logging.info("Starting HuggingFace sync...")

    # TODO: Implement HF sync job
    logging.warning("HF sync job not yet implemented")

    logging.info("HuggingFace sync completed")


@app.command()
def migrate(
    batch_size: int = typer.Option(1000, help="Batch size for migration"),
    max_records: Optional[int] = typer.Option(None, help="Max records to migrate (for testing)"),
) -> None:
    """Migrate data from HuggingFace to PostgreSQL."""
    import sys
    sys.path.insert(0, str(__file__).replace("src/data_platform/cli.py", "scripts"))

    from scripts.migrate_hf_to_postgres import main as migrate_main

    logging.info(f"Starting HF to PostgreSQL migration (batch_size={batch_size}, max_records={max_records})")

    migrate_main(batch_size=batch_size, max_records=max_records)

    logging.info("Migration completed")


@app.command("sync-typesense")
def sync_typesense(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
    full_sync: bool = typer.Option(False, help="Force full sync (overwrite existing)"),
    batch_size: int = typer.Option(1000, help="Batch size for Typesense upsert"),
    max_records: Optional[int] = typer.Option(None, help="Max records to sync (for testing)"),
) -> None:
    """
    Sync news from PostgreSQL to Typesense.

    Reads news with themes and embeddings from PostgreSQL and indexes them in Typesense.
    Supports incremental updates (upsert) and full reload.

    Note: Always includes content embeddings in the sync.
    """
    from data_platform.jobs.typesense import sync_to_typesense

    logging.info(f"Syncing to Typesense from {start_date} to {end_date or start_date}")
    logging.info(f"Mode: {'Full sync' if full_sync else 'Incremental'}")

    stats = sync_to_typesense(
        start_date=start_date,
        end_date=end_date,
        full_sync=full_sync,
        batch_size=batch_size,
        limit=max_records,
    )

    logging.info(
        f"Typesense sync completed: {stats['total_indexed']} indexed, "
        f"{stats['errors']} errors, {stats['total_fetched']} fetched"
    )


@app.command("typesense-delete")
def typesense_delete(
    collection_name: str = typer.Option("news", help="Collection name to delete"),
    confirm: bool = typer.Option(False, "--confirm", help="Skip confirmation prompt"),
) -> None:
    """
    Delete a Typesense collection.

    WARNING: This permanently deletes all documents in the collection.
    Use --confirm to skip the interactive confirmation prompt.
    """
    from data_platform.jobs.typesense import delete_typesense_collection

    if not confirm:
        logging.warning(f"About to delete collection '{collection_name}'")
        logging.warning("Use --confirm to skip this prompt")

    success = delete_typesense_collection(collection_name=collection_name, confirm=confirm)

    if success:
        logging.info(f"Collection '{collection_name}' deleted successfully")
    else:
        logging.warning(f"Collection '{collection_name}' was not deleted")


@app.command("typesense-list")
def typesense_list() -> None:
    """
    List all Typesense collections.

    Shows collection names and document counts.
    """
    from data_platform.jobs.typesense import list_typesense_collections

    collections = list_typesense_collections()

    if not collections:
        logging.info("No collections found")
    else:
        logging.info(f"Found {len(collections)} collection(s)")


if __name__ == "__main__":
    app()
