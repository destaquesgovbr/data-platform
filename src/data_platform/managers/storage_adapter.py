"""
Storage Adapter for DestaquesGovBr.

Provides a unified interface for storage backends (PostgreSQL, HuggingFace)
supporting dual-write mode for migration phases.
"""

import os
from enum import Enum
from typing import Optional, List, OrderedDict, Dict, Any
from datetime import datetime

import pandas as pd
from loguru import logger

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.models.news import NewsInsert


class StorageBackend(Enum):
    """Available storage backends."""

    HUGGINGFACE = "huggingface"
    POSTGRES = "postgres"
    DUAL_WRITE = "dual_write"


class StorageAdapter:
    """
    Unified storage adapter that abstracts backend selection.

    Supports three modes:
    - HUGGINGFACE: Write to HuggingFace only (legacy)
    - POSTGRES: Write to PostgreSQL only (target)
    - DUAL_WRITE: Write to both backends (migration phase)

    Read source can be configured separately via STORAGE_READ_FROM env var.

    Environment variables:
    - STORAGE_BACKEND: Backend for writes (huggingface, postgres, dual_write)
    - STORAGE_READ_FROM: Backend for reads (huggingface, postgres)
    - DATABASE_URL: PostgreSQL connection string
    - HF_TOKEN: HuggingFace token (for HF backend)
    """

    def __init__(
        self,
        backend: Optional[StorageBackend] = None,
        read_from: Optional[StorageBackend] = None,
        postgres_manager: Optional[PostgresManager] = None,
        dataset_manager: Optional[Any] = None,  # DatasetManager from scraper
    ):
        """
        Initialize StorageAdapter.

        Args:
            backend: Storage backend for writes. Defaults to STORAGE_BACKEND env var.
            read_from: Backend for reads. Defaults to STORAGE_READ_FROM env var.
            postgres_manager: Optional pre-configured PostgresManager.
            dataset_manager: Optional pre-configured DatasetManager (HuggingFace).
        """
        # Determine write backend
        backend_str = os.getenv("STORAGE_BACKEND", "huggingface")
        self.backend = backend or StorageBackend(backend_str.lower())

        # Determine read backend
        # STORAGE_READ_FROM can be explicitly set to override read source
        read_str_env = os.getenv("STORAGE_READ_FROM")
        if read_from:
            self.read_from = read_from
        elif read_str_env:
            # Explicit STORAGE_READ_FROM takes precedence
            self.read_from = StorageBackend(read_str_env.lower())
        elif self.backend == StorageBackend.DUAL_WRITE:
            # During dual-write without explicit read source, default to HF (legacy)
            self.read_from = StorageBackend.HUGGINGFACE
        else:
            # Default: read from same backend as write
            self.read_from = self.backend

        logger.info(f"StorageAdapter initialized: write={self.backend.value}, read={self.read_from.value}")

        # Lazy-load managers
        self._postgres_manager = postgres_manager
        self._dataset_manager = dataset_manager

    @property
    def postgres(self) -> PostgresManager:
        """Lazy-load PostgresManager."""
        if self._postgres_manager is None:
            logger.info("Initializing PostgresManager...")
            self._postgres_manager = PostgresManager()
            self._postgres_manager.load_cache()
        return self._postgres_manager

    @property
    def huggingface(self) -> Any:
        """Lazy-load DatasetManager (HuggingFace)."""
        if self._dataset_manager is None:
            # Import here to avoid circular dependencies
            # DatasetManager is in the scraper repo
            try:
                from dataset_manager import DatasetManager
                logger.info("Initializing DatasetManager (HuggingFace)...")
                self._dataset_manager = DatasetManager()
            except ImportError:
                raise ImportError(
                    "DatasetManager not found. Make sure the scraper package is installed "
                    "or STORAGE_BACKEND is set to 'postgres'."
                )
        return self._dataset_manager

    def insert(self, new_data: OrderedDict, allow_update: bool = False) -> int:
        """
        Insert new records into storage.

        Follows DatasetManager interface for compatibility.

        Args:
            new_data: OrderedDict with arrays for each column
            allow_update: If True, update existing records with same unique_id

        Returns:
            Number of records inserted/updated
        """
        total_records = len(new_data.get("unique_id", []))
        logger.info(f"Inserting {total_records} records (backend={self.backend.value})")

        errors = []
        inserted = 0

        if self.backend in (StorageBackend.HUGGINGFACE, StorageBackend.DUAL_WRITE):
            try:
                self.huggingface.insert(new_data, allow_update=allow_update)
                logger.success(f"HuggingFace: inserted {total_records} records")
                inserted = total_records
            except Exception as e:
                logger.error(f"HuggingFace insert failed: {e}")
                errors.append(("huggingface", str(e)))

        if self.backend in (StorageBackend.POSTGRES, StorageBackend.DUAL_WRITE):
            try:
                news_list = self._convert_to_news_insert(new_data)
                inserted = self.postgres.insert(news_list, allow_update=allow_update)
                logger.success(f"PostgreSQL: inserted {inserted} records")
            except Exception as e:
                logger.error(f"PostgreSQL insert failed: {e}")
                errors.append(("postgres", str(e)))

        if errors:
            if self.backend == StorageBackend.DUAL_WRITE:
                # In dual-write mode, log errors but don't fail if at least one backend succeeded
                for backend, error in errors:
                    logger.warning(f"Backend {backend} failed: {error}")
                if len(errors) == 2:
                    raise Exception(f"All backends failed: {errors}")
            else:
                raise Exception(f"Insert failed: {errors[0]}")

        return inserted

    def update(self, updated_df: pd.DataFrame) -> int:
        """
        Update existing records.

        Follows DatasetManager interface for compatibility.

        Args:
            updated_df: DataFrame with updates (must include unique_id column)

        Returns:
            Number of records updated
        """
        total_records = len(updated_df)
        logger.info(f"Updating {total_records} records (backend={self.backend.value})")

        errors = []
        updated = 0

        if self.backend in (StorageBackend.HUGGINGFACE, StorageBackend.DUAL_WRITE):
            try:
                self.huggingface.update(updated_df)
                logger.success(f"HuggingFace: updated {total_records} records")
                updated = total_records
            except Exception as e:
                logger.error(f"HuggingFace update failed: {e}")
                errors.append(("huggingface", str(e)))

        if self.backend in (StorageBackend.POSTGRES, StorageBackend.DUAL_WRITE):
            try:
                updated = self._update_postgres(updated_df)
                logger.success(f"PostgreSQL: updated {updated} records")
            except Exception as e:
                logger.error(f"PostgreSQL update failed: {e}")
                errors.append(("postgres", str(e)))

        if errors:
            if self.backend == StorageBackend.DUAL_WRITE:
                for backend, error in errors:
                    logger.warning(f"Backend {backend} failed: {error}")
                if len(errors) == 2:
                    raise Exception(f"All backends failed: {errors}")
            else:
                raise Exception(f"Update failed: {errors[0]}")

        return updated

    def get(
        self,
        min_date: str,
        max_date: str,
        agency: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get records from storage by date range.

        Follows DatasetManager interface for compatibility.

        Args:
            min_date: Minimum date (YYYY-MM-DD)
            max_date: Maximum date (YYYY-MM-DD)
            agency: Optional agency filter

        Returns:
            DataFrame with matching records
        """
        logger.info(f"Getting records: {min_date} to {max_date} (read_from={self.read_from.value})")

        if self.read_from == StorageBackend.HUGGINGFACE:
            return self.huggingface.get(min_date, max_date, agency=agency)
        else:
            return self._get_postgres(min_date, max_date, agency)

    def get_count(self) -> int:
        """Get total record count from read backend."""
        if self.read_from == StorageBackend.POSTGRES:
            return self.postgres.get_count()
        else:
            # For HuggingFace, load dataset and get length
            df = self.huggingface.get("1900-01-01", "2099-12-31")
            return len(df)

    # -------------------------------------------------------------------------
    # Private helper methods
    # -------------------------------------------------------------------------

    def _convert_to_news_insert(self, data: OrderedDict) -> List[NewsInsert]:
        """Convert OrderedDict data to list of NewsInsert objects."""
        news_list = []

        # Get number of records
        num_records = len(data.get("unique_id", []))

        def safe_get(field: str, default=None):
            """Safely get a value from data at index i, with default if missing."""
            values = data.get(field, [])
            return values[i] if i < len(values) else default

        for i in range(num_records):
            try:
                # Extract fields with defaults
                published_at = safe_get("published_at")
                if published_at is None:
                    logger.warning(f"Skipping record {i}: missing published_at")
                    continue

                # Parse datetime if string
                if isinstance(published_at, str):
                    published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))

                # Resolve agency_key to agency_id
                agency_key = safe_get("agency", "")
                agency = self.postgres._agencies_by_key.get(agency_key)
                if not agency:
                    logger.warning(f"Skipping record {i}: unknown agency '{agency_key}'")
                    continue
                agency_id = agency.id

                # Resolve theme codes to IDs (themes may not be present for new records)
                theme_l1_code = safe_get("theme_1_level_1_code")
                theme_l2_code = safe_get("theme_1_level_2_code")
                theme_l3_code = safe_get("theme_1_level_3_code")
                most_specific_code = safe_get("most_specific_theme_code")

                theme_l1_id = self._resolve_theme_id(theme_l1_code)
                theme_l2_id = self._resolve_theme_id(theme_l2_code)
                theme_l3_id = self._resolve_theme_id(theme_l3_code)
                most_specific_id = self._resolve_theme_id(most_specific_code)

                news = NewsInsert(
                    unique_id=safe_get("unique_id", ""),
                    agency_id=agency_id,
                    agency_key=agency_key,
                    agency_name=agency.name,
                    theme_l1_id=theme_l1_id,
                    theme_l2_id=theme_l2_id,
                    theme_l3_id=theme_l3_id,
                    most_specific_theme_id=most_specific_id,
                    title=safe_get("title", ""),
                    url=safe_get("url"),
                    image_url=safe_get("image"),  # HF uses 'image', not 'image_url'
                    video_url=safe_get("video_url"),
                    category=safe_get("category"),
                    tags=safe_get("tags") or [],
                    content=safe_get("content"),
                    editorial_lead=safe_get("editorial_lead"),
                    subtitle=safe_get("subtitle"),
                    summary=safe_get("summary"),
                    published_at=published_at,
                    updated_datetime=self._parse_datetime(safe_get("updated_datetime")),
                    extracted_at=self._parse_datetime(safe_get("extracted_at")),
                )
                news_list.append(news)
            except Exception as e:
                logger.warning(f"Error converting record {i}: {e}")
                continue

        return news_list

    def _resolve_theme_id(self, theme_code: Optional[str]) -> Optional[int]:
        """Resolve theme code to ID using cache."""
        if not theme_code:
            return None
        theme = self.postgres._themes_by_code.get(theme_code)
        return theme.id if theme else None

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except:
                return None
        # Handle pandas Timestamp
        if hasattr(value, "to_pydatetime"):
            return value.to_pydatetime()
        return None

    def _update_postgres(self, updated_df: pd.DataFrame) -> int:
        """Update records in PostgreSQL from DataFrame.

        Handles mapping between HuggingFace column names and PostgreSQL column names,
        particularly for theme fields (code → id).
        """
        updated = 0

        # Column mapping: HF column → PG column (with special handling)
        THEME_COLUMNS = {
            "theme_1_level_1_code": "theme_l1_id",
            "theme_1_level_2_code": "theme_l2_id",
            "theme_1_level_3_code": "theme_l3_id",
            "most_specific_theme_code": "most_specific_theme_id",
        }

        # Columns to skip (HF-only or derived)
        SKIP_COLUMNS = {
            "unique_id",
            "theme_1_level_1",
            "theme_1_level_1_label",
            "theme_1_level_2_label",
            "theme_1_level_3_label",
            "most_specific_theme_label",
        }

        for _, row in updated_df.iterrows():
            unique_id = row.get("unique_id")
            if not unique_id:
                continue

            # Build updates dict from row
            updates = {}
            for col, value in row.items():
                if col in SKIP_COLUMNS:
                    continue
                if pd.isna(value):
                    continue

                # Handle theme columns (code → id)
                if col in THEME_COLUMNS:
                    theme_id = self._resolve_theme_id(value)
                    if theme_id is not None:
                        updates[THEME_COLUMNS[col]] = theme_id
                else:
                    updates[col] = value

            if updates:
                try:
                    if self.postgres.update(unique_id, updates):
                        updated += 1
                except Exception as e:
                    logger.warning(f"Error updating {unique_id}: {e}")

        return updated

    def _get_postgres(
        self,
        min_date: str,
        max_date: str,
        agency: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get records from PostgreSQL with date range filtering."""
        import json
        from psycopg2.extras import RealDictCursor
        from data_platform.models.news import News

        conn = self.postgres.get_connection()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Build query with date range
            query = """
                SELECT * FROM news
                WHERE published_at >= %s::date AND published_at < (%s::date + INTERVAL '1 day')
            """
            params = [min_date, max_date]

            if agency:
                query += " AND agency_key = %s"
                params.append(agency)

            query += " ORDER BY published_at DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Convert content_embedding from JSON string to list for Pydantic validation
            for row in rows:
                if row.get('content_embedding') and isinstance(row['content_embedding'], str):
                    try:
                        row['content_embedding'] = json.loads(row['content_embedding'])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Failed to parse content_embedding for record {row.get('unique_id')}")
                        row['content_embedding'] = None

            records = [News(**row) for row in rows]
        finally:
            cursor.close()
            self.postgres.put_connection(conn)

        # Convert to DataFrame matching HuggingFace format
        if not records:
            return pd.DataFrame()

        data = []
        for record in records:
            data.append({
                "unique_id": record.unique_id,
                "agency": record.agency_key,
                "title": record.title,
                "url": record.url,
                "image": record.image_url,  # Match HF column name
                "video_url": record.video_url,
                "category": record.category,
                "tags": record.tags,
                "content": record.content,
                "editorial_lead": record.editorial_lead,
                "subtitle": record.subtitle,
                "summary": record.summary,
                "published_at": record.published_at,
                "updated_datetime": record.updated_datetime,
                "extracted_at": record.extracted_at,
                "theme_1_level_1_code": self._get_theme_code(record.theme_l1_id),
                "theme_1_level_2_code": self._get_theme_code(record.theme_l2_id),
                "theme_1_level_3_code": self._get_theme_code(record.theme_l3_id),
                "most_specific_theme_code": self._get_theme_code(record.most_specific_theme_id),
                "content_embedding": record.content_embedding,
                "embedding_generated_at": record.embedding_generated_at,
            })

        return pd.DataFrame(data)

    def _get_theme_code(self, theme_id: Optional[int]) -> Optional[str]:
        """Get theme code from ID using cache."""
        if theme_id is None:
            return None
        theme = self.postgres._themes_by_id.get(theme_id)
        return theme.code if theme else None
