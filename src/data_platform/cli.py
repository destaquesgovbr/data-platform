"""
Unified CLI for the DestaquesGovBr data platform.

Commands:
- scrape: Scrape gov.br news from specified agencies
- scrape-ebc: Scrape EBC (Agencia Brasil, TV Brasil) news
- upload-cogfy: Upload news to Cogfy for AI enrichment
- enrich: Enrich news with AI-generated themes from Cogfy
- sync-hf: Sync PostgreSQL data to HuggingFace
- migrate: Migrate data from HuggingFace to PostgreSQL
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
    help="Data platform for DestaquesGovBr - scraping, enrichment, and storage"
)


@app.command()
def scrape(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
    agencies: Optional[str] = typer.Option(None, help="Comma-separated agency codes"),
    allow_update: bool = typer.Option(False, help="Allow updating existing records"),
    sequential: bool = typer.Option(True, help="Process agencies sequentially"),
) -> None:
    """Scrape gov.br news from specified agencies."""
    from data_platform.managers import StorageAdapter
    from data_platform.scrapers.scrape_manager import ScrapeManager

    logging.info(f"Starting gov.br scrape from {start_date} to {end_date or start_date}")

    storage = StorageAdapter()
    manager = ScrapeManager(storage)
    agency_list = agencies.split(",") if agencies else None

    manager.run_scraper(
        agency_list,
        start_date,
        end_date or start_date,
        sequential,
        allow_update
    )

    logging.info("Scraping completed")


@app.command("scrape-ebc")
def scrape_ebc(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
    allow_update: bool = typer.Option(False, help="Allow updating existing records"),
    sequential: bool = typer.Option(True, help="Process sequentially"),
) -> None:
    """Scrape EBC (Agencia Brasil, TV Brasil) news."""
    from data_platform.managers import StorageAdapter
    from data_platform.scrapers.ebc_scrape_manager import EBCScrapeManager

    logging.info(f"Starting EBC scrape from {start_date} to {end_date or start_date}")

    storage = StorageAdapter()
    manager = EBCScrapeManager(storage)

    manager.run_scraper(
        start_date,
        end_date or start_date,
        sequential,
        allow_update
    )

    logging.info("EBC scraping completed")


@app.command("upload-cogfy")
def upload_cogfy(
    start_date: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = typer.Option(None, help="End date (YYYY-MM-DD)"),
) -> None:
    """Upload news to Cogfy for AI enrichment."""
    import os
    from data_platform.cogfy.upload_manager import UploadToCogfyManager

    server_url = os.getenv("COGFY_SERVER_URL", "https://api.cogfy.com")
    collection_name = os.getenv("COGFY_COLLECTION_NAME", "govbrnews")

    logging.info(f"Uploading news to Cogfy from {start_date} to {end_date or start_date}")

    manager = UploadToCogfyManager(server_url, collection_name)
    manager.upload_date_range(start_date, end_date or start_date)

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
    manager.enrich_date_range(start_date, end_date or start_date)

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


if __name__ == "__main__":
    app()
