import hashlib
import logging
import os
from collections import OrderedDict
from datetime import date, datetime
from typing import Any

import yaml  # type: ignore[import-untyped]

from data_platform.scrapers.ebc_webscraper import EBCWebScraper

# Set up logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class EBCScrapeManager:
    """
    A class that focuses on:
      - Running EBC web scrapers for the specified date ranges.
      - Preprocessing, transforming, and preparing raw EBC news data into a well-structured format
        ready for dataset creation and analysis.
      - Generating unique identifiers for news items based on their attributes (agency,
        published date, and title).
      - Converting raw data from a list-of-dictionaries format into a columnar (OrderedDict) format.
      - Merging new data with an existing dataset, ensuring no duplicates by comparing unique IDs.
      - Sorting the combined dataset by specified criteria (e.g., agency and publication date).
      - Preparing the final processed data into columnar format suitable for integration with
        a dataset manager.
    """

    def __init__(self, storage: Any):
        """
        Initialize EBCScrapeManager with a storage backend.

        Args:
            storage: Storage backend (StorageWrapper or DatasetManager)
        """
        self.dataset_manager = storage  # Keep attribute name for compatibility

    def _load_urls_from_yaml(self, file_name: str, source: str | None = None) -> list[str]:
        """
        Load URLs from a YAML file located in the same directory as this script.

        Expected format:
            source_key:
              url: str
              active: bool  # optional, defaults to True
              disabled_reason: str  # optional
              disabled_date: str  # optional

        :param file_name: The name of the YAML file.
        :param source: Specific source key to filter URLs. If None, load all active URLs.
        :return: A list of URLs.
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, "config", file_name)

        with open(file_path) as f:
            sources = yaml.safe_load(f)["sources"]

        if source:
            if source not in sources:
                raise ValueError(f"Source '{source}' not found in the YAML file.")
            source_data = sources[source]
            if self._is_source_inactive(source, source_data):
                raise ValueError(f"Source '{source}' is inactive.")
            return [self._extract_url(source_data)]

        # Load all active sources
        urls = []
        inactive_sources = []

        for source_key, source_data in sources.items():
            if self._is_source_inactive(source_key, source_data):
                inactive_sources.append(source_key)
                continue
            urls.append(self._extract_url(source_data))

        if inactive_sources:
            logging.info(
                f"Filtered {len(inactive_sources)} inactive sources: "
                f"{', '.join(sorted(inactive_sources))}"
            )

        return urls

    def _extract_url(self, source_data: dict[str, Any]) -> str:
        """
        Extract URL from source data.

        :param source_data: Dict with 'url' key.
        :return: The URL string.
        """
        return str(source_data["url"])

    def _is_source_inactive(self, source_key: str, source_data: dict[str, Any]) -> bool:
        """
        Check if source is inactive.

        :param source_key: Source identifier for logging.
        :param source_data: Dict with optional 'active' key.
        :return: True if source should be skipped.
        """
        is_active = source_data.get("active", True)

        if not is_active:
            reason = source_data.get("disabled_reason", "No reason provided")
            logging.debug(f"Skipping inactive source '{source_key}': {reason}")

        return not is_active

    def run_scraper(
        self,
        min_date: str,
        max_date: str,
        sequential: bool,
        allow_update: bool = False,
        sources: list[str] | None = None,
    ):
        """
        Executes the EBC web scraping process for the given date range.

        :param min_date: The minimum date for filtering news.
        :param max_date: The maximum date for filtering news.
        :param sequential: Whether to scrape sequentially (True) or in bulk (False).
        :param allow_update: If True, overwrite existing entries in the dataset.
        :param sources: A list of source names to scrape news from. If None, all active sources are scraped.
        """
        try:
            all_urls = []
            # Load URLs for each source in the list
            if sources:
                for source in sources:
                    try:
                        urls = self._load_urls_from_yaml("ebc_urls.yaml", source)
                        all_urls.extend(urls)
                    except ValueError as e:
                        logging.warning(f"Skipping source '{source}': {e}")
            else:
                # Load all source URLs if sources list is None or empty
                all_urls = self._load_urls_from_yaml("ebc_urls.yaml")

            webscrapers = [EBCWebScraper(min_date, url, max_date=max_date) for url in all_urls]

            if sequential:
                for scraper in webscrapers:
                    scraped_data = scraper.scrape_news()
                    if scraped_data:
                        logging.info(
                            f"Appending {len(scraped_data)} news from {scraper.base_url} to HF dataset."
                        )
                        self._process_and_upload_data(scraped_data, allow_update)
                    else:
                        logging.info(f"No news found for {scraper.base_url}.")
            else:
                all_news_data = []
                for scraper in webscrapers:
                    scraped_data = scraper.scrape_news()
                    if scraped_data:
                        all_news_data.extend(scraped_data)
                    else:
                        logging.info(f"No news found for {scraper.base_url}.")

                if all_news_data:
                    logging.info("Appending all collected news to HF dataset.")
                    self._process_and_upload_data(all_news_data, allow_update)
                else:
                    logging.info("No news found for any EBC source.")
        except ValueError as e:
            logging.error(e)

    def _process_and_upload_data(self, new_data: list[dict], allow_update: bool):
        """
        Process the EBC news data and upload it to the dataset, with the option to update existing entries.

        :param new_data: The list of EBC news items to process.
        :param allow_update: If True, overwrite existing entries in the dataset.
        """
        # Convert EBC data format to govbrnews format
        processed_data = self._convert_ebc_to_govbr_format(new_data)

        # Preprocess the data (add unique IDs, reorder columns)
        processed_data = self._preprocess_data(processed_data)

        # Insert into dataset
        self.dataset_manager.insert(processed_data, allow_update=allow_update)

    def _convert_ebc_to_govbr_format(self, ebc_data: list[dict]) -> list[dict]:
        """
        Convert EBC data format to match the govbrnews schema.

        :param ebc_data: List of EBC news items as dictionaries.
        :return: List of news items in govbrnews format.
        """
        converted_data = []

        for item in ebc_data:
            # Skip items with errors
            if item.get("error"):
                logging.warning(f"Skipping item with error: {item['error']}")
                continue

            # Get datetimes (already extracted by EBCWebScraper)
            published_dt = item.get("published_datetime")
            updated_datetime = item.get("updated_datetime")

            # Use the agency from the scraped data (either 'agencia_brasil' or 'tvbrasil')
            # Fallback to 'ebc' if not specified
            agency = item.get("agency", "ebc")

            # Extract editorial_lead (e.g., program name for TV Brasil)
            editorial_lead = item.get("editorial_lead", "").strip() or None

            converted_item = {
                "title": item.get("title", "").strip(),
                "url": item.get("url", "").strip(),
                "published_at": published_dt if published_dt else None,
                "updated_datetime": updated_datetime,
                "category": "Notícias",  # EBC doesn't have specific categories like gov.br
                "tags": item.get("tags", []),  # Now extracted from article pages
                "editorial_lead": editorial_lead,  # Program name for TV Brasil (e.g., "Caminhos da Reportagem")
                "subtitle": None,  # EBC articles don't typically have subtitles in the same format
                "content": item.get("content", "").strip(),
                "image": item.get("image", "").strip(),
                "video_url": item.get("video_url", "").strip(),
                "agency": agency,
                "extracted_at": datetime.now(),
            }

            # Only add items with essential data
            if converted_item["title"] and converted_item["url"] and converted_item["content"]:
                converted_data.append(converted_item)
            else:
                logging.warning(f"Skipping incomplete item: {item.get('url', 'unknown URL')}")

        return converted_data

    def _parse_ebc_date(self, date_str: str) -> date:
        """
        Parse EBC date string to date object.
        Expected format: "16/09/2025 - 13:40"

        :param date_str: Date string from EBC.
        :return: Date object or current date if parsing fails.
        """
        try:
            if not date_str:
                return datetime.now().date()

            # Remove extra whitespace and split by ' - '
            date_part = date_str.strip().split(" - ")[0]
            # Parse the date part (DD/MM/YYYY)
            return datetime.strptime(date_part, "%d/%m/%Y").date()
        except Exception as e:
            logging.warning(f"Could not parse date '{date_str}': {e}. Using current date.")
            return datetime.now().date()

    def _preprocess_data(self, data: list[dict[str, str]]) -> OrderedDict:
        """
        Preprocess data by:
        - Adding the unique_id column.
        - Reordering columns to match govbrnews format.

        :param data: List of news items as dictionaries.
        :return: An OrderedDict with the processed data.
        """
        # Generate unique_id for each record
        for item in data:
            item["unique_id"] = self._generate_unique_id(
                item.get("agency", ""),
                item.get("published_at", ""),
                item.get("title", ""),
            )

        # Convert to columnar format
        if not data:
            return OrderedDict()

        column_data = {key: [item.get(key, None) for item in data] for key in data[0].keys()}

        # Reorder columns to match govbrnews format
        ordered_column_data = OrderedDict()
        if "unique_id" in column_data:
            ordered_column_data["unique_id"] = column_data.pop("unique_id")
        if "agency" in column_data:
            ordered_column_data["agency"] = column_data.pop("agency")
        if "published_at" in column_data:
            ordered_column_data["published_at"] = column_data.pop("published_at")
        if "updated_datetime" in column_data:
            ordered_column_data["updated_datetime"] = column_data.pop("updated_datetime")

        # Add remaining columns in order (matching govbrnews schema)
        for key in [
            "title",
            "editorial_lead",
            "subtitle",
            "url",
            "category",
            "tags",
            "content",
            "image",
            "video_url",
            "extracted_at",
        ]:
            if key in column_data:
                ordered_column_data[key] = column_data.pop(key)

        # Add any remaining columns
        ordered_column_data.update(column_data)

        return ordered_column_data

    def _generate_unique_id(self, agency: str, published_at_value, title: str) -> str:
        """
        Generate a unique identifier based on the agency, published_at, and title.

        :param agency: The agency name.
        :param published_at_value: The published_at date of the news item (string format or date object).
        :param title: The title of the news item.
        :return: A unique hash string.
        """
        date_str = (
            published_at_value.isoformat()
            if isinstance(published_at_value, date)
            else str(published_at_value)
        )
        hash_input = f"{agency}_{date_str}_{title}".encode()
        return hashlib.md5(hash_input).hexdigest()
