"""
Batch processing utilities for data-platform.

This module provides centralized batch processing functions
used across the codebase for handling large datasets efficiently.

Functions:
    batch_iterator: Iterate over data in batches
    process_in_batches: Process items in batches with error handling
    chunked: Split an iterable into chunks
"""

import logging
from typing import Iterator, TypeVar, Callable, Iterable, Any

import pandas as pd

logger = logging.getLogger(__name__)

T = TypeVar("T")


def batch_iterator(
    total_count: int,
    batch_size: int,
    fetch_fn: Callable[[int, int], pd.DataFrame],
) -> Iterator[pd.DataFrame]:
    """
    Generic batch iterator for fetching DataFrames.

    Yields DataFrames in batches, useful for processing large datasets
    without loading everything into memory at once.

    Args:
        total_count: Total number of records to fetch
        batch_size: Number of records per batch
        fetch_fn: Function that takes (offset, limit) and returns DataFrame

    Yields:
        DataFrame batches

    Examples:
        >>> def fetch(offset, limit):
        ...     return df.iloc[offset:offset + limit]
        >>> for batch in batch_iterator(1000, 100, fetch):
        ...     process(batch)
    """
    if total_count <= 0:
        return

    offset = 0
    batch_num = 0

    while offset < total_count:
        batch_num += 1
        df = fetch_fn(offset, batch_size)

        if df.empty:
            break

        logger.debug(
            f"Batch {batch_num}: fetched {len(df)} records "
            f"(offset: {offset}, total: {total_count})"
        )

        yield df
        offset += batch_size


def process_in_batches(
    items: list[T],
    batch_size: int,
    process_fn: Callable[[list[T]], Any],
    on_error: str = "continue",
) -> dict[str, int]:
    """
    Process a list of items in batches with error handling.

    Useful for bulk operations like database inserts or API calls
    where processing in batches is more efficient.

    Args:
        items: List of items to process
        batch_size: Number of items per batch
        process_fn: Function to process each batch
        on_error: Error handling strategy:
            - "continue": Continue processing remaining batches (default)
            - "stop": Stop processing on first error

    Returns:
        Dictionary with statistics:
            - total: Total number of items
            - processed: Number of successfully processed items
            - errors: Number of items in failed batches

    Examples:
        >>> def save_batch(batch):
        ...     db.insert_many(batch)
        >>> stats = process_in_batches(records, 100, save_batch)
        >>> print(f"Processed {stats['processed']} of {stats['total']}")
    """
    stats = {
        "total": len(items),
        "processed": 0,
        "errors": 0,
        "batches_total": 0,
        "batches_success": 0,
        "batches_failed": 0,
    }

    if not items:
        return stats

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        stats["batches_total"] += 1

        try:
            process_fn(batch)
            stats["processed"] += len(batch)
            stats["batches_success"] += 1
        except Exception as e:
            stats["errors"] += len(batch)
            stats["batches_failed"] += 1
            logger.error(f"Batch {stats['batches_total']} failed: {e}")

            if on_error == "stop":
                break

    return stats


def chunked(iterable: Iterable[T], chunk_size: int) -> Iterator[list[T]]:
    """
    Split an iterable into chunks of specified size.

    Unlike batch_iterator which works with DataFrames, this works
    with any iterable and yields lists.

    Args:
        iterable: Any iterable to split
        chunk_size: Size of each chunk

    Yields:
        Lists of items, each with at most chunk_size items

    Examples:
        >>> list(chunked([1, 2, 3, 4, 5], 2))
        [[1, 2], [3, 4], [5]]

        >>> for chunk in chunked(range(1000), 100):
        ...     process_chunk(chunk)
    """
    chunk = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def calculate_batch_stats(
    total: int,
    batch_size: int,
) -> dict[str, int]:
    """
    Calculate batch processing statistics before execution.

    Useful for logging or progress reporting.

    Args:
        total: Total number of items
        batch_size: Size of each batch

    Returns:
        Dictionary with:
            - total: Total items
            - batch_size: Batch size
            - num_batches: Number of batches
            - last_batch_size: Size of the last batch

    Examples:
        >>> stats = calculate_batch_stats(1000, 100)
        >>> print(f"Will process {stats['num_batches']} batches")
    """
    if total <= 0:
        return {
            "total": 0,
            "batch_size": batch_size,
            "num_batches": 0,
            "last_batch_size": 0,
        }

    num_batches = (total + batch_size - 1) // batch_size
    last_batch_size = total % batch_size or batch_size

    return {
        "total": total,
        "batch_size": batch_size,
        "num_batches": num_batches,
        "last_batch_size": last_batch_size,
    }
