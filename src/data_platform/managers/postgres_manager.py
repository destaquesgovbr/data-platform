"""
PostgreSQL Storage Manager for DestaquesGovBr.

Manages news storage in PostgreSQL with connection pooling, caching, and error handling.
"""

import os
import subprocess
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote_plus

import pandas as pd
from loguru import logger
from psycopg2 import extensions, pool
from psycopg2.extras import RealDictCursor, execute_values
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from data_platform.models.news import Agency, News, NewsInsert, Theme


class PostgresManager:
    """
    PostgreSQL storage manager with connection pooling and caching.

    Features:
    - Connection pooling for performance
    - In-memory cache for agencies and themes
    - Batch insert/update operations
    """

    def __init__(
        self,
        connection_string: str | None = None,
        min_connections: int = 1,
        max_connections: int = 10,
    ):
        """
        Initialize PostgresManager.

        Args:
            connection_string: PostgreSQL connection string. If None, auto-detect.
            min_connections: Minimum number of pooled connections
            max_connections: Maximum number of pooled connections
        """
        self.connection_string = connection_string or self._get_connection_string()
        self.pool = self._create_pool(min_connections, max_connections)

        # SQLAlchemy engine for pandas operations (NullPool avoids duplicate pooling)
        self._engine = create_engine(self.connection_string, poolclass=NullPool)

        # In-memory caches
        self._agencies_by_key: dict[str, Agency] = {}
        self._agencies_by_id: dict[int, Agency] = {}
        self._themes_by_code: dict[str, Theme] = {}
        self._themes_by_id: dict[int, Theme] = {}
        self._cache_loaded = False

    def _get_connection_string(self) -> str:
        """
        Get database connection string from environment, Secret Manager, or use localhost.

        Priority:
        1. DATABASE_URL environment variable
        2. Secret Manager (for Cloud deployment)
        3. Cloud SQL Proxy detection

        Returns:
            PostgreSQL connection string
        """
        # Check for DATABASE_URL environment variable first (for local development)
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            logger.info("Using DATABASE_URL from environment")
            return database_url

        try:
            # Try Secret Manager for Cloud deployment
            result = subprocess.run(
                [
                    "gcloud",
                    "secrets",
                    "versions",
                    "access",
                    "latest",
                    "--secret=destaquesgovbr-postgres-connection-string",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            secret_conn_str = result.stdout.strip()

            # Parse password from connection string
            if "://" in secret_conn_str and "@" in secret_conn_str:
                after_protocol = secret_conn_str.split("://")[1]
                user_pass, _ = after_protocol.rsplit("@", 1)
                if ":" in user_pass:
                    _, password = user_pass.split(":", 1)
                else:
                    password = "password"
            else:
                password = "password"

        except subprocess.CalledProcessError:
            logger.warning("Failed to fetch connection string from Secret Manager")
            password = "password"

        # Check if Cloud SQL Proxy is running
        proxy_check = subprocess.run(
            ["pgrep", "-f", "cloud-sql-proxy"],
            capture_output=True,
        )

        if proxy_check.returncode == 0:
            logger.info("Cloud SQL Proxy detected, using localhost connection")
            encoded_password = quote_plus(password)
            return (
                f"postgresql://destaquesgovbr_app:{encoded_password}@127.0.0.1:5432/destaquesgovbr"
            )

        # Return original secret for direct connection
        return secret_conn_str

    def _create_pool(self, min_conn: int, max_conn: int) -> pool.SimpleConnectionPool:
        """
        Create connection pool.

        Args:
            min_conn: Minimum connections
            max_conn: Maximum connections

        Returns:
            Connection pool
        """
        logger.info(f"Creating connection pool (min={min_conn}, max={max_conn})")
        return pool.SimpleConnectionPool(
            min_conn,
            max_conn,
            self.connection_string,
        )

    def get_connection(self) -> extensions.connection:
        """
        Get connection from pool.

        Returns:
            Database connection
        """
        return self.pool.getconn()

    def put_connection(self, conn: extensions.connection) -> None:
        """
        Return connection to pool.

        Args:
            conn: Database connection
        """
        self.pool.putconn(conn)

    def close_all(self) -> None:
        """Close all connections in pool."""
        logger.info("Closing all database connections")
        self.pool.closeall()
        self._engine.dispose()

    def load_cache(self) -> None:
        """Load agencies and themes into memory cache."""
        if self._cache_loaded:
            logger.debug("Cache already loaded")
            return

        logger.info("Loading agencies and themes into cache...")
        conn = self.get_connection()

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Load agencies
            cursor.execute("SELECT * FROM agencies")
            agencies = cursor.fetchall()
            for row in agencies:
                agency = Agency(**row)
                self._agencies_by_key[agency.key] = agency
                self._agencies_by_id[cast(int, agency.id)] = agency

            # Load themes
            cursor.execute("SELECT * FROM themes")
            themes = cursor.fetchall()
            for row in themes:
                theme = Theme(**row)
                self._themes_by_code[theme.code] = theme
                self._themes_by_id[cast(int, theme.id)] = theme

            self._cache_loaded = True
            logger.success(
                f"Cache loaded: {len(self._agencies_by_key)} agencies, "
                f"{len(self._themes_by_code)} themes"
            )

        finally:
            cursor.close()
            self.put_connection(conn)

    def get_agency_by_key(self, key: str) -> Agency | None:
        """
        Get agency by key (cached).

        Args:
            key: Agency key

        Returns:
            Agency or None
        """
        if not self._cache_loaded:
            self.load_cache()
        return self._agencies_by_key.get(key)

    def get_theme_by_code(self, code: str) -> Theme | None:
        """
        Get theme by code (cached).

        Args:
            code: Theme code

        Returns:
            Theme or None
        """
        if not self._cache_loaded:
            self.load_cache()
        return self._themes_by_code.get(code)

    def insert(self, news: list[NewsInsert], allow_update: bool = False) -> int:
        """
        Insert news records (batch operation).

        Args:
            news: List of news to insert
            allow_update: If True, update existing records (ON CONFLICT UPDATE)

        Returns:
            Number of records inserted/updated

        Raises:
            ValueError: If news list is empty
            psycopg2.Error: On database error
        """
        if not news:
            raise ValueError("News list cannot be empty")

        # Deduplicate by unique_id (keep first occurrence)
        # Same pattern as HuggingFace backend's drop_duplicates()
        # This handles race conditions where the same article appears on multiple pages
        seen_ids: set[str] = set()
        deduped_news: list[NewsInsert] = []
        for n in news:
            if n.unique_id not in seen_ids:
                seen_ids.add(n.unique_id)
                deduped_news.append(n)

        if len(deduped_news) < len(news):
            logger.info(f"Removed {len(news) - len(deduped_news)} duplicate items by unique_id")

        news = deduped_news

        logger.info(f"Inserting {len(news)} news records (allow_update={allow_update})")

        conn = self.get_connection()
        inserted = 0

        try:
            cursor = conn.cursor()

            # Prepare INSERT query
            columns = [
                "unique_id",
                "agency_id",
                "theme_l1_id",
                "theme_l2_id",
                "theme_l3_id",
                "most_specific_theme_id",
                "title",
                "url",
                "image_url",
                "video_url",
                "category",
                "tags",
                "content",
                "editorial_lead",
                "subtitle",
                "summary",
                "published_at",
                "updated_datetime",
                "extracted_at",
                "agency_key",
                "agency_name",
            ]

            # Build values list
            values = []
            for n in news:
                values.append(
                    (
                        n.unique_id,
                        n.agency_id,
                        n.theme_l1_id,
                        n.theme_l2_id,
                        n.theme_l3_id,
                        n.most_specific_theme_id,
                        n.title,
                        n.url,
                        n.image_url,
                        n.video_url,
                        n.category,
                        n.tags,
                        n.content,
                        n.editorial_lead,
                        n.subtitle,
                        n.summary,
                        n.published_at,
                        n.updated_datetime,
                        n.extracted_at,
                        n.agency_key,
                        n.agency_name,
                    )
                )

            # Base INSERT
            insert_query = f"""
                INSERT INTO news ({", ".join(columns)})
                VALUES %s
            """

            if allow_update:
                # ON CONFLICT UPDATE
                update_cols = [
                    c for c in columns if c not in ["unique_id", "agency_id", "published_at"]
                ]
                update_set = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])
                insert_query += f"""
                    ON CONFLICT (unique_id)
                    DO UPDATE SET {update_set}, updated_at = NOW()
                """
            else:
                # ON CONFLICT DO NOTHING
                insert_query += " ON CONFLICT (unique_id) DO NOTHING"

            # Execute batch insert
            execute_values(cursor, insert_query, values)
            inserted = cursor.rowcount
            conn.commit()

            logger.success(f"Inserted/updated {inserted} news records")
            return inserted  # type: ignore[no-any-return]

        except Exception as e:
            conn.rollback()
            logger.error(f"Error inserting news: {e}")
            raise

        finally:
            cursor.close()
            self.put_connection(conn)

    def update(self, unique_id: str, updates: dict[str, Any]) -> bool:
        """
        Update news record by unique_id.

        Args:
            unique_id: Unique identifier
            updates: Dictionary of field: value to update

        Returns:
            True if updated, False if not found

        Raises:
            ValueError: If updates is empty
            psycopg2.Error: On database error
        """
        if not updates:
            raise ValueError("Updates dictionary cannot be empty")

        logger.debug(f"Updating news {unique_id}: {updates}")

        conn = self.get_connection()

        try:
            cursor = conn.cursor()

            # Build SET clause
            set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
            values = list(updates.values()) + [unique_id]

            query = f"""
                UPDATE news
                SET {set_clause}, updated_at = NOW()
                WHERE unique_id = %s
            """

            cursor.execute(query, values)
            updated = cursor.rowcount > 0
            conn.commit()

            if updated:
                logger.debug(f"Updated news {unique_id}")
            else:
                logger.warning(f"News {unique_id} not found")

            return updated  # type: ignore[no-any-return]

        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating news {unique_id}: {e}")
            raise

        finally:
            cursor.close()
            self.put_connection(conn)

    def get(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order_by: str = "published_at DESC",
    ) -> list[News]:
        """
        Get news records with filters.

        Args:
            filters: Dictionary of field: value filters (AND condition)
            limit: Maximum number of records
            offset: Number of records to skip
            order_by: ORDER BY clause (e.g., "published_at DESC")

        Returns:
            List of News objects
        """
        conn = self.get_connection()

        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = "SELECT * FROM news"
            params = []

            # Add WHERE clause
            if filters:
                where_clauses = []
                for key, value in filters.items():
                    where_clauses.append(f"{key} = %s")
                    params.append(value)
                query += " WHERE " + " AND ".join(where_clauses)

            # Add ORDER BY
            query += f" ORDER BY {order_by}"

            # Add LIMIT/OFFSET
            if limit:
                query += f" LIMIT {limit}"
            if offset:
                query += f" OFFSET {offset}"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [News(**row) for row in rows]

        finally:
            cursor.close()
            self.put_connection(conn)

    def get_by_unique_id(self, unique_id: str) -> News | None:
        """
        Get single news by unique_id.

        Args:
            unique_id: Unique identifier

        Returns:
            News object or None
        """
        results = self.get(filters={"unique_id": unique_id}, limit=1)
        return results[0] if results else None

    def count(self, filters: dict[str, Any] | None = None) -> int:
        """
        Count news records with optional filters.

        Args:
            filters: Dictionary of field: value filters (AND condition)

        Returns:
            Number of matching records
        """
        conn = self.get_connection()

        try:
            cursor = conn.cursor()

            query = "SELECT COUNT(*) FROM news"
            params = []

            if filters:
                where_clauses = []
                for key, value in filters.items():
                    where_clauses.append(f"{key} = %s")
                    params.append(value)
                query += " WHERE " + " AND ".join(where_clauses)

            cursor.execute(query, params)
            count = cursor.fetchone()[0]

            return count  # type: ignore[no-any-return]

        finally:
            cursor.close()
            self.put_connection(conn)

    def _build_typesense_query(self) -> str:
        """
        Build the SQL query for Typesense data fetching.

        Always includes content_embedding field.

        Returns:
            SQL query string (without WHERE clause parameters)
        """
        query = """
            SELECT
                n.unique_id,
                n.agency_key as agency,
                n.title,
                n.url,
                n.image_url as image,
                n.video_url,
                n.category,
                n.content,
                n.summary,
                n.subtitle,
                n.editorial_lead,
                EXTRACT(EPOCH FROM n.published_at)::bigint as published_at_ts,
                EXTRACT(EPOCH FROM n.extracted_at)::bigint as extracted_at_ts,
                EXTRACT(YEAR FROM n.published_at)::int as published_year,
                EXTRACT(MONTH FROM n.published_at)::int as published_month,
                t1.code as theme_1_level_1_code,
                t1.label as theme_1_level_1_label,
                t2.code as theme_1_level_2_code,
                t2.label as theme_1_level_2_label,
                t3.code as theme_1_level_3_code,
                t3.label as theme_1_level_3_label,
                tm.code as most_specific_theme_code,
                tm.label as most_specific_theme_label,
                n.tags,
                n.content_embedding
        """

        query += """
            FROM news n
            LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
            LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
            LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
            LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
        """

        return query

    def count_news_for_typesense(
        self,
        start_date: str,
        end_date: str | None = None,
    ) -> int:
        """
        Count news records for a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to start_date

        Returns:
            Number of records in the date range
        """
        end_date = end_date or start_date
        conn = self.get_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM news
                    WHERE published_at >= %s
                      AND published_at < %s::date + INTERVAL '1 day'
                    """,
                    [start_date, end_date],
                )
                return cur.fetchone()[0]  # type: ignore[no-any-return]
        finally:
            self.put_connection(conn)

    def iter_news_for_typesense(
        self,
        start_date: str,
        end_date: str | None = None,
        batch_size: int = 5000,
    ) -> Iterator[pd.DataFrame]:
        """
        Iterate over news in batches for memory-efficient Typesense indexing.

        This method yields DataFrames in batches to avoid loading all data
        into memory at once, which is important for large datasets (300k+ records).

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to start_date
            batch_size: Number of records per batch (default: 5000)

        Yields:
            DataFrame batches with news data ready for Typesense indexing (includes embeddings)
        """
        end_date = end_date or start_date

        # Get total count first
        total_count = self.count_news_for_typesense(start_date, end_date)
        logger.info(
            f"Total news to fetch for Typesense: {total_count} "
            f"(date range: {start_date} to {end_date})"
        )

        if total_count == 0:
            return

        # Build base query
        base_query = self._build_typesense_query()
        base_query += """
            WHERE n.published_at >= %s
              AND n.published_at < %s::date + INTERVAL '1 day'
            ORDER BY n.published_at DESC
            LIMIT %s OFFSET %s
        """

        offset = 0
        batch_num = 0

        while offset < total_count:
            params = (start_date, end_date, batch_size, offset)
            df = pd.read_sql_query(base_query, self._engine, params=params)

            if df.empty:
                break

            batch_num += 1
            logger.info(
                f"Fetched batch {batch_num}: {len(df)} records "
                f"(offset: {offset}, total: {total_count})"
            )

            yield df

            offset += batch_size

    def get_news_for_typesense(
        self,
        start_date: str,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """
        Get news with theme labels for Typesense indexing.

        WARNING: This method loads all data into memory at once.
        For large datasets, use iter_news_for_typesense() instead.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to start_date
            limit: Maximum number of records

        Returns:
            DataFrame with news data ready for Typesense indexing (includes embeddings)
        """
        end_date = end_date or start_date

        # Build query
        query = self._build_typesense_query()
        query += """
            WHERE n.published_at >= %s
              AND n.published_at < %s::date + INTERVAL '1 day'
            ORDER BY n.published_at DESC
        """

        params: list[str | int] = [start_date, end_date]

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        df = pd.read_sql_query(query, self._engine, params=tuple(params))

        logger.info(
            f"Fetched {len(df)} news for Typesense (date range: {start_date} to {end_date})"
        )

        return df

    def __enter__(self) -> "PostgresManager":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit."""
        self.close_all()
