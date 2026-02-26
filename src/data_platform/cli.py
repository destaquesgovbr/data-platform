"""
Unified CLI for the DestaquesGovBr data platform.

Commands:
- upload-cogfy: Upload news to Cogfy for AI enrichment
- enrich: Enrich news with AI-generated themes from Cogfy
- sync-hf: Sync PostgreSQL data to HuggingFace
- migrate: Migrate data from HuggingFace to PostgreSQL
- sync-typesense: Sync news from PostgreSQL to Typesense
- typesense-delete: Delete a Typesense collection
- typesense-list: List all Typesense collections

Note: Scraping commands moved to standalone scraper repo.
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
    help="Data platform for DestaquesGovBr - enrichment, embeddings, and storage"
)


@app.command("upload-cogfy")
def upload_cogfy(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
) -> None:
    """Upload news to Cogfy for AI enrichment."""
    import os
    from data_platform.cogfy.upload_manager import UploadToCogfyManager

    server_url = os.getenv("COGFY_SERVER_URL", "https://api.cogfy.com/")
    collection_name = os.getenv("COGFY_COLLECTION_NAME", "noticiasgovbr-all-news")

    logging.info(f"Uploading news to Cogfy from {start_date} to {end_date or start_date}")

    manager = UploadToCogfyManager(server_url, collection_name)
    manager.upload(start_date=start_date, end_date=end_date or start_date)

    logging.info("Cogfy upload completed")


@app.command()
def enrich(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
) -> None:
    """Enrich news with AI-generated themes from Cogfy."""
    from data_platform.cogfy.enrichment_manager import EnrichmentManager

    logging.info(f"Enriching news from {start_date} to {end_date or start_date}")

    manager = EnrichmentManager()
    manager.enrich_dataset_with_themes(start_date=start_date, end_date=end_date or start_date)

    logging.info("Enrichment completed")


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
