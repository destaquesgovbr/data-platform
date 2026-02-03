"""
Embedding Generator for semantic search.

Generates embeddings for news articles using the Embeddings API (Cloud Run service).
Phase 4.7: Embeddings Semânticos

Scope: Only 2025 news (have AI-generated summaries from Cogfy)
Model: paraphrase-multilingual-mpnet-base-v2 (768 dimensions)
Input: title + " " + summary (fallback to content if summary missing)
"""

import logging
import os
from datetime import datetime
from typing import Any

import httpx
import numpy as np
import psycopg2
from psycopg2.extras import execute_batch

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Generates semantic embeddings for news articles via HTTP API."""

    # Model configuration (must match the API)
    MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    EMBEDDING_DIM = 768

    # Performance configuration
    DEFAULT_BATCH_SIZE = 100
    MAX_TEXT_LENGTH = 512  # Model's max sequence length
    API_TIMEOUT = 120  # seconds

    def __init__(
        self,
        database_url: str | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
    ):
        """
        Initialize the embedding generator.

        Args:
            database_url: PostgreSQL connection string. If None, reads from DATABASE_URL env var.
            api_url: Embeddings API URL. If None, reads from EMBEDDINGS_API_URL env var.
            api_key: API key for authentication. If None, reads from EMBEDDINGS_API_KEY env var.
        """
        self.database_url: str = database_url or os.getenv("DATABASE_URL") or ""
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        self.api_url: str = api_url or os.getenv("EMBEDDINGS_API_URL") or ""
        if not self.api_url:
            raise ValueError("EMBEDDINGS_API_URL environment variable is required")

        self.api_key: str = api_key or os.getenv("EMBEDDINGS_API_KEY") or ""
        if not self.api_key:
            raise ValueError("EMBEDDINGS_API_KEY environment variable is required")

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Get a PostgreSQL connection."""
        return psycopg2.connect(self.database_url)

    def _fetch_news_without_embeddings(
        self, start_date: str, end_date: str | None = None, limit: int | None = None
    ) -> list[tuple[int, str, str | None, str | None]]:
        """
        Fetch news records that don't have embeddings yet.

        Scope: Only 2025 news (published_at >= '2025-01-01')

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD). If None, uses start_date.
            limit: Maximum number of records to fetch.

        Returns:
            List of (id, title, summary, content) tuples
        """
        end_date = end_date or start_date

        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT id, title, summary, content
                    FROM news
                    WHERE published_at >= %s
                      AND published_at < %s::date + INTERVAL '1 day'
                      AND content_embedding IS NULL
                    ORDER BY published_at DESC
                """

                params: list[Any] = [start_date, end_date]

                if limit:
                    query += " LIMIT %s"
                    params.append(limit)

                cur.execute(query, params)
                results: list[tuple[int, str, str | None, str | None]] = cur.fetchall()

                logger.info(
                    f"Found {len(results)} news without embeddings "
                    f"(date range: {start_date} to {end_date})"
                )

                return results
        finally:
            conn.close()

    def _prepare_text_for_embedding(
        self, title: str, summary: str | None, content: str | None
    ) -> str:
        """
        Prepare text for embedding generation.

        Strategy: title + " " + summary (fallback to content if summary missing)

        Args:
            title: News title
            summary: AI-generated summary from Cogfy (may be None for older news)
            content: Raw news content (fallback)

        Returns:
            Prepared text string
        """
        # Always include title
        text_parts = [title.strip() if title else ""]

        # Prefer summary (AI-generated, cleaner), fallback to content
        if summary and summary.strip():
            text_parts.append(summary.strip())
        elif content and content.strip():
            # Use first 500 chars of content as fallback
            text_parts.append(content.strip()[:500])

        # Join with space
        text = " ".join(part for part in text_parts if part)

        # Truncate to model's max length (rough estimate, tokenizer will handle exactly)
        if len(text) > self.MAX_TEXT_LENGTH * 4:  # ~4 chars per token estimate
            text = text[: self.MAX_TEXT_LENGTH * 4]

        return text

    def _generate_embeddings_batch(self, texts: list[str]) -> np.ndarray:
        """
        Generate embeddings for a batch of texts via HTTP API.

        Args:
            texts: List of text strings

        Returns:
            numpy array of shape (len(texts), 768)
        """
        # Call the embeddings API
        with httpx.Client(timeout=self.API_TIMEOUT) as client:
            response = client.post(
                f"{self.api_url.rstrip('/')}/generate",
                json={"texts": texts},
                headers={
                    "X-API-Key": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()

        result = response.json()

        # Validate response
        if "embeddings" not in result:
            raise ValueError("Invalid API response: missing 'embeddings' key")

        embeddings = np.array(result["embeddings"], dtype=np.float32)

        if embeddings.shape[1] != self.EMBEDDING_DIM:
            raise ValueError(
                f"Unexpected embedding dimension: {embeddings.shape[1]} (expected {self.EMBEDDING_DIM})"
            )

        logger.debug(
            f"Generated {result.get('count', len(texts))} embeddings "
            f"(model: {result.get('model', 'unknown')}, dim: {result.get('dimension', 'unknown')})"
        )

        return embeddings

    def _update_embeddings_batch(self, news_ids: list[int], embeddings: np.ndarray) -> int:
        """
        Update news records with generated embeddings.

        Args:
            news_ids: List of news IDs
            embeddings: numpy array of embeddings (shape: (len(news_ids), 768))

        Returns:
            Number of records updated
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                # Prepare data for batch update
                # Convert numpy array to list for PostgreSQL
                update_data = [
                    (
                        embeddings[i].tolist(),  # Convert numpy array to Python list
                        datetime.utcnow(),
                        news_ids[i],
                    )
                    for i in range(len(news_ids))
                ]

                # Batch update
                execute_batch(
                    cur,
                    """
                        UPDATE news
                        SET content_embedding = %s::vector,
                            embedding_generated_at = %s
                        WHERE id = %s
                    """,
                    update_data,
                    page_size=100,
                )

                conn.commit()
                return len(news_ids)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating embeddings: {e}")
            raise
        finally:
            conn.close()

    def generate_embeddings(
        self,
        start_date: str,
        end_date: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_records: int | None = None,
    ) -> dict[str, int]:
        """
        Generate embeddings for news articles.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD). If None, uses start_date.
            batch_size: Number of records to process per batch
            max_records: Maximum number of records to process (for testing)

        Returns:
            Dictionary with statistics:
                - processed: Total records processed
                - successful: Records successfully updated
                - failed: Records that failed
        """
        logger.info(
            f"Starting embedding generation for date range: {start_date} to {end_date or start_date}"
        )
        logger.info(f"Using Embeddings API at: {self.api_url}")

        # Fetch news without embeddings
        news_records = self._fetch_news_without_embeddings(start_date, end_date, max_records)

        if not news_records:
            logger.info("No records found without embeddings")
            return {"processed": 0, "successful": 0, "failed": 0}

        # Process in batches
        total_processed = 0
        total_successful = 0
        total_failed = 0

        for i in range(0, len(news_records), batch_size):
            batch = news_records[i : i + batch_size]
            batch_ids = [rec[0] for rec in batch]

            try:
                # Prepare texts
                texts = [
                    self._prepare_text_for_embedding(title=rec[1], summary=rec[2], content=rec[3])
                    for rec in batch
                ]

                # Generate embeddings via API
                logger.info(
                    f"Generating embeddings for batch {i // batch_size + 1} ({len(batch)} records)"
                )
                embeddings = self._generate_embeddings_batch(texts)

                # Update database
                updated = self._update_embeddings_batch(batch_ids, embeddings)

                total_successful += updated
                logger.info(f"Batch {i // batch_size + 1}: {updated} records updated successfully")

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"API error processing batch {i // batch_size + 1}: "
                    f"{e.response.status_code} - {e.response.text}"
                )
                total_failed += len(batch)

            except Exception as e:
                logger.error(f"Error processing batch {i // batch_size + 1}: {e}")
                total_failed += len(batch)

            total_processed += len(batch)

        logger.info(
            f"Embedding generation complete: {total_successful} successful, "
            f"{total_failed} failed, {total_processed} total"
        )

        return {
            "processed": total_processed,
            "successful": total_successful,
            "failed": total_failed,
        }
