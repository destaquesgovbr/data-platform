"""
Typesense Sync Manager for embeddings.

Syncs embeddings from PostgreSQL to Typesense for semantic search.
Phase 4.7: Embeddings Semânticos
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
import typesense

logger = logging.getLogger(__name__)


class TypesenseSyncManager:
    """Syncs embeddings from PostgreSQL to Typesense."""

    COLLECTION_NAME = "news"
    BATCH_SIZE = 1000  # Typesense batch upsert size

    def __init__(
        self,
        database_url: Optional[str] = None,
        typesense_host: Optional[str] = None,
        typesense_port: Optional[str] = None,
        typesense_api_key: Optional[str] = None
    ):
        """
        Initialize the Typesense sync manager.

        Args:
            database_url: PostgreSQL connection string
            typesense_host: Typesense host
            typesense_port: Typesense port
            typesense_api_key: Typesense API key

        All args default to environment variables if not provided.
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        # Typesense configuration
        self.typesense_host = typesense_host or os.getenv("TYPESENSE_HOST", "localhost")
        self.typesense_port = typesense_port or os.getenv("TYPESENSE_PORT", "8108")
        self.typesense_api_key = typesense_api_key or os.getenv("TYPESENSE_API_KEY")

        if not self.typesense_api_key:
            raise ValueError("TYPESENSE_API_KEY environment variable is required")

        # Typesense client (lazy init)
        self._client: Optional[typesense.Client] = None

    @property
    def client(self) -> typesense.Client:
        """Lazy load Typesense client."""
        if self._client is None:
            self._client = typesense.Client({
                'nodes': [{
                    'host': self.typesense_host,
                    'port': self.typesense_port,
                    'protocol': 'http'
                }],
                'api_key': self.typesense_api_key,
                'connection_timeout_seconds': 10
            })
            logger.info(f"Connected to Typesense at {self.typesense_host}:{self.typesense_port}")
        return self._client

    def _get_connection(self):
        """Get a PostgreSQL connection."""
        return psycopg2.connect(self.database_url)

    def _check_collection_schema(self) -> Dict:
        """
        Check if the Typesense collection has the content_embedding field.

        Returns:
            Collection schema dict

        Raises:
            ValueError: If collection doesn't exist or doesn't have embedding field
        """
        try:
            collection = self.client.collections[self.COLLECTION_NAME].retrieve()
            logger.info(f"Collection '{self.COLLECTION_NAME}' found with {collection['num_documents']} documents")

            # Check if content_embedding field exists
            embedding_field = next(
                (f for f in collection['fields'] if f['name'] == 'content_embedding'),
                None
            )

            if not embedding_field:
                logger.warning(
                    f"Collection '{self.COLLECTION_NAME}' does not have 'content_embedding' field. "
                    "You need to recreate the collection with the updated schema."
                )
                logger.warning(
                    "See _plan/README.md section 4.7.10 for Typesense schema update instructions."
                )

            return collection

        except typesense.exceptions.ObjectNotFound:
            raise ValueError(
                f"Collection '{self.COLLECTION_NAME}' not found. "
                "Create it first with the schema that includes content_embedding field."
            )

    def _fetch_news_with_new_embeddings(
        self,
        start_date: str,
        end_date: Optional[str] = None,
        last_sync_timestamp: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Fetch news records with embeddings that need to be synced.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            last_sync_timestamp: Only fetch records updated after this timestamp
            limit: Maximum number of records to fetch

        Returns:
            List of news records as dicts
        """
        end_date = end_date or start_date

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Build query - with JOINs to get theme labels
                query = """
                    SELECT
                        n.unique_id,
                        n.agency_key,
                        n.agency_name,
                        n.title,
                        n.url,
                        n.image_url,
                        n.category,
                        n.content,
                        n.summary,
                        n.subtitle,
                        n.editorial_lead,
                        n.published_at,
                        n.extracted_at,
                        t1.code as theme_l1_code,
                        t1.label as theme_l1_label,
                        t2.code as theme_l2_code,
                        t2.label as theme_l2_label,
                        t3.code as theme_l3_code,
                        t3.label as theme_l3_label,
                        tm.code as most_specific_theme_code,
                        tm.label as most_specific_theme_label,
                        n.content_embedding,
                        n.embedding_generated_at
                    FROM news n
                    LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
                    LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
                    LEFT JOIN themes t3 ON n.theme_l3_id = t3.id
                    LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
                    WHERE n.published_at >= %s
                      AND n.published_at < %s::date + INTERVAL '1 day'
                      AND n.content_embedding IS NOT NULL
                      AND n.published_at >= '2025-01-01'  -- Phase 4.7: Only 2025 news
                """

                params = [start_date, end_date]

                # Incremental sync: only fetch recently updated embeddings
                if last_sync_timestamp:
                    query += " AND n.embedding_generated_at > %s"
                    params.append(last_sync_timestamp)

                query += " ORDER BY n.published_at DESC"

                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                cur.execute(query, params)

                # Convert to list of dicts
                columns = [desc[0] for desc in cur.description]
                records = [dict(zip(columns, row)) for row in cur.fetchall()]

                logger.info(
                    f"Found {len(records)} news with embeddings to sync "
                    f"(date range: {start_date} to {end_date})"
                )

                return records
        finally:
            conn.close()

    def _get_last_sync_timestamp(self) -> Optional[datetime]:
        """
        Get the timestamp of the last successful sync to Typesense.

        Returns:
            Last sync timestamp or None if no successful sync found
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT completed_at
                    FROM sync_log
                    WHERE operation = 'typesense_embeddings_sync'
                      AND status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT 1
                """)

                result = cur.fetchone()
                if result:
                    logger.info(f"Last sync timestamp: {result[0]}")
                    return result[0]
                else:
                    logger.info("No previous sync found")
                    return None
        except psycopg2.errors.UndefinedTable:
            # sync_log table doesn't exist yet
            logger.info("sync_log table doesn't exist, treating as first sync")
            return None
        finally:
            conn.close()

    def _prepare_typesense_document(self, news: Dict) -> Dict:
        """
        Prepare a news record for Typesense indexing.

        Args:
            news: News record dict from PostgreSQL

        Returns:
            Document dict for Typesense
        """
        doc = {
            'unique_id': news['unique_id'],
            'published_at': int(news['published_at'].timestamp()) if news['published_at'] else 0
        }

        # Add optional fields
        optional_fields = [
            'agency_key', 'title', 'url', 'image_url', 'category',
            'content', 'summary', 'subtitle', 'editorial_lead',
            'theme_l1_code', 'theme_l1_label',
            'theme_l2_code', 'theme_l2_label',
            'theme_l3_code', 'theme_l3_label',
            'most_specific_theme_code', 'most_specific_theme_label'
        ]

        for field in optional_fields:
            if news.get(field):
                doc[field] = str(news[field]).strip()

        # Add extracted_at timestamp
        if news.get('extracted_at'):
            doc['extracted_at'] = int(news['extracted_at'].timestamp())

        # Add published_year and published_month for faceting
        if news.get('published_at'):
            doc['published_year'] = news['published_at'].year
            doc['published_month'] = news['published_at'].month

        # Add content_embedding (convert from string/memoryview to list)
        if news.get('content_embedding'):
            # PostgreSQL returns vector as string like '[1.0, 2.0, ...]'
            # or as memoryview bytes
            embedding = news['content_embedding']

            if isinstance(embedding, str):
                # Parse string representation
                embedding_list = json.loads(embedding)
            elif isinstance(embedding, (bytes, memoryview)):
                # Convert bytes to list of floats (pgvector binary format)
                # This is complex, so we'll just skip for now and handle in query
                import struct
                data = bytes(embedding)
                # pgvector binary format: dimension (2 bytes) + floats (4 bytes each)
                dim = struct.unpack('!H', data[:2])[0]
                embedding_list = list(struct.unpack(f'!{dim}f', data[2:]))
            elif isinstance(embedding, list):
                # Already a list
                embedding_list = embedding
            else:
                logger.warning(f"Unknown embedding type: {type(embedding)}")
                embedding_list = None

            if embedding_list:
                doc['content_embedding'] = embedding_list

        return doc

    def _upsert_documents_batch(self, documents: List[Dict]) -> int:
        """
        Upsert a batch of documents to Typesense.

        Args:
            documents: List of document dicts

        Returns:
            Number of successfully upserted documents
        """
        try:
            # Import documents (upsert mode)
            results = self.client.collections[self.COLLECTION_NAME].documents.import_(
                documents,
                {'action': 'upsert'}
            )

            # Count successes and failures
            successes = sum(1 for r in results if r.get('success'))
            failures = len(results) - successes

            if failures > 0:
                logger.warning(f"Batch had {failures} failures")
                # Log first few failures
                for r in results[:5]:
                    if not r.get('success'):
                        logger.warning(f"Failed document: {r}")

            return successes

        except Exception as e:
            logger.error(f"Error upserting batch: {e}")
            raise

    def sync_embeddings(
        self,
        start_date: str,
        end_date: Optional[str] = None,
        full_sync: bool = False,
        batch_size: int = BATCH_SIZE,
        max_records: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Sync embeddings from PostgreSQL to Typesense.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            full_sync: If True, sync all embeddings. If False, only sync updated ones.
            batch_size: Number of documents to upsert per batch
            max_records: Maximum number of records to sync (for testing)

        Returns:
            Dictionary with statistics:
                - processed: Total records processed
                - successful: Records successfully synced
                - failed: Records that failed
        """
        logger.info(
            f"Starting embedding sync to Typesense for date range: {start_date} to {end_date or start_date}"
        )

        # Check collection schema
        self._check_collection_schema()

        # Get last sync timestamp (for incremental sync)
        last_sync_timestamp = None if full_sync else self._get_last_sync_timestamp()

        # Fetch news with embeddings
        news_records = self._fetch_news_with_new_embeddings(
            start_date, end_date, last_sync_timestamp, max_records
        )

        if not news_records:
            logger.info("No records to sync")
            return {"processed": 0, "successful": 0, "failed": 0}

        # Process in batches
        total_processed = 0
        total_successful = 0
        total_failed = 0

        for i in range(0, len(news_records), batch_size):
            batch = news_records[i:i + batch_size]

            try:
                # Prepare documents
                documents = [self._prepare_typesense_document(news) for news in batch]

                # Upsert batch
                logger.info(f"Syncing batch {i // batch_size + 1} ({len(batch)} documents)")
                successful = self._upsert_documents_batch(documents)

                total_successful += successful
                total_failed += (len(batch) - successful)

            except Exception as e:
                logger.error(f"Error processing batch {i // batch_size + 1}: {e}")
                total_failed += len(batch)

            total_processed += len(batch)

        logger.info(
            f"Embedding sync complete: {total_successful} successful, "
            f"{total_failed} failed, {total_processed} total"
        )

        return {
            "processed": total_processed,
            "successful": total_successful,
            "failed": total_failed
        }
