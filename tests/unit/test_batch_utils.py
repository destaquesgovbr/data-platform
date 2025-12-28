"""
Tests for batch processing utilities.

These tests ensure that:
1. batch_iterator correctly iterates over data
2. process_in_batches handles errors correctly
3. chunked splits iterables correctly
4. Statistics are calculated correctly
"""

import pytest
import pandas as pd


class TestBatchIterator:
    """Tests for batch_iterator function."""

    def test_single_batch(self):
        """When total fits in one batch, yields one batch."""
        from data_platform.utils.batch import batch_iterator

        results = []

        def fetch(offset, limit):
            return pd.DataFrame({"id": range(offset, min(offset + limit, 10))})

        for batch in batch_iterator(total_count=10, batch_size=20, fetch_fn=fetch):
            results.append(batch)

        assert len(results) == 1
        assert len(results[0]) == 10

    def test_multiple_batches(self):
        """Correctly divides into multiple batches."""
        from data_platform.utils.batch import batch_iterator

        results = []

        def fetch(offset, limit):
            end = min(offset + limit, 100)
            if offset >= 100:
                return pd.DataFrame()
            return pd.DataFrame({"id": range(offset, end)})

        for batch in batch_iterator(total_count=100, batch_size=30, fetch_fn=fetch):
            results.append(batch)

        assert len(results) == 4  # 30 + 30 + 30 + 10
        assert sum(len(b) for b in results) == 100

    def test_empty_total(self):
        """Zero total_count returns no batches."""
        from data_platform.utils.batch import batch_iterator

        results = list(
            batch_iterator(
                total_count=0, batch_size=10, fetch_fn=lambda o, l: pd.DataFrame()
            )
        )
        assert len(results) == 0

    def test_negative_total(self):
        """Negative total_count returns no batches."""
        from data_platform.utils.batch import batch_iterator

        results = list(
            batch_iterator(
                total_count=-10, batch_size=10, fetch_fn=lambda o, l: pd.DataFrame()
            )
        )
        assert len(results) == 0

    def test_stops_on_empty_dataframe(self):
        """Stops iteration when fetch returns empty DataFrame."""
        from data_platform.utils.batch import batch_iterator

        call_count = 0

        def fetch(offset, limit):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                return pd.DataFrame()
            return pd.DataFrame({"id": [1, 2, 3]})

        results = list(
            batch_iterator(total_count=1000, batch_size=10, fetch_fn=fetch)
        )
        assert len(results) == 2


class TestProcessInBatches:
    """Tests for process_in_batches function."""

    def test_successful_processing(self):
        """All batches processed successfully."""
        from data_platform.utils.batch import process_in_batches

        processed_items = []

        def process(batch):
            processed_items.extend(batch)

        stats = process_in_batches(
            items=list(range(100)), batch_size=30, process_fn=process
        )

        assert stats["total"] == 100
        assert stats["processed"] == 100
        assert stats["errors"] == 0
        assert stats["batches_total"] == 4
        assert stats["batches_success"] == 4
        assert stats["batches_failed"] == 0
        assert len(processed_items) == 100

    def test_with_errors_continue(self):
        """Continues processing after error (default behavior)."""
        from data_platform.utils.batch import process_in_batches

        call_count = 0

        def process(batch):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated error")

        stats = process_in_batches(
            items=list(range(100)), batch_size=30, process_fn=process, on_error="continue"
        )

        assert stats["errors"] == 30  # Second batch failed
        assert stats["processed"] == 70  # Other 3 batches OK
        assert stats["batches_failed"] == 1
        assert stats["batches_success"] == 3

    def test_with_errors_stop(self):
        """Stops processing on error when on_error='stop'."""
        from data_platform.utils.batch import process_in_batches

        call_count = 0

        def process(batch):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Simulated error")

        stats = process_in_batches(
            items=list(range(100)), batch_size=30, process_fn=process, on_error="stop"
        )

        assert stats["errors"] == 30  # Second batch failed
        assert stats["processed"] == 30  # Only first batch processed
        assert stats["batches_failed"] == 1
        assert stats["batches_success"] == 1
        assert stats["batches_total"] == 2  # Stopped after second batch

    def test_empty_list(self):
        """Empty list returns zero stats."""
        from data_platform.utils.batch import process_in_batches

        stats = process_in_batches(items=[], batch_size=10, process_fn=lambda x: None)

        assert stats["total"] == 0
        assert stats["processed"] == 0
        assert stats["errors"] == 0
        assert stats["batches_total"] == 0

    def test_batch_size_larger_than_items(self):
        """Handles batch_size larger than items."""
        from data_platform.utils.batch import process_in_batches

        processed_items = []

        def process(batch):
            processed_items.extend(batch)

        stats = process_in_batches(
            items=[1, 2, 3], batch_size=100, process_fn=process
        )

        assert stats["total"] == 3
        assert stats["processed"] == 3
        assert stats["batches_total"] == 1
        assert len(processed_items) == 3


class TestChunked:
    """Tests for chunked function."""

    def test_exact_division(self):
        """Items divide evenly into chunks."""
        from data_platform.utils.batch import chunked

        result = list(chunked([1, 2, 3, 4, 5, 6], 2))

        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_uneven_division(self):
        """Last chunk has remaining items."""
        from data_platform.utils.batch import chunked

        result = list(chunked([1, 2, 3, 4, 5], 2))

        assert result == [[1, 2], [3, 4], [5]]

    def test_chunk_size_larger_than_items(self):
        """Single chunk when chunk_size > len(items)."""
        from data_platform.utils.batch import chunked

        result = list(chunked([1, 2, 3], 10))

        assert result == [[1, 2, 3]]

    def test_empty_iterable(self):
        """Empty iterable yields nothing."""
        from data_platform.utils.batch import chunked

        result = list(chunked([], 10))

        assert result == []

    def test_generator_input(self):
        """Works with generators."""
        from data_platform.utils.batch import chunked

        result = list(chunked(range(5), 2))

        assert result == [[0, 1], [2, 3], [4]]

    def test_single_item_chunks(self):
        """Chunk size 1 yields individual items."""
        from data_platform.utils.batch import chunked

        result = list(chunked([1, 2, 3], 1))

        assert result == [[1], [2], [3]]


class TestCalculateBatchStats:
    """Tests for calculate_batch_stats function."""

    def test_exact_division(self):
        """Stats for exact division."""
        from data_platform.utils.batch import calculate_batch_stats

        stats = calculate_batch_stats(total=100, batch_size=25)

        assert stats["total"] == 100
        assert stats["batch_size"] == 25
        assert stats["num_batches"] == 4
        assert stats["last_batch_size"] == 25

    def test_uneven_division(self):
        """Stats for uneven division."""
        from data_platform.utils.batch import calculate_batch_stats

        stats = calculate_batch_stats(total=100, batch_size=30)

        assert stats["total"] == 100
        assert stats["batch_size"] == 30
        assert stats["num_batches"] == 4
        assert stats["last_batch_size"] == 10

    def test_zero_total(self):
        """Stats for zero items."""
        from data_platform.utils.batch import calculate_batch_stats

        stats = calculate_batch_stats(total=0, batch_size=10)

        assert stats["total"] == 0
        assert stats["num_batches"] == 0
        assert stats["last_batch_size"] == 0

    def test_single_batch(self):
        """Stats when everything fits in one batch."""
        from data_platform.utils.batch import calculate_batch_stats

        stats = calculate_batch_stats(total=5, batch_size=100)

        assert stats["total"] == 5
        assert stats["num_batches"] == 1
        assert stats["last_batch_size"] == 5


class TestImports:
    """Tests for module imports."""

    def test_import_from_utils(self):
        """Can import from utils package."""
        from data_platform.utils import (
            batch_iterator,
            process_in_batches,
            chunked,
            calculate_batch_stats,
        )

        assert callable(batch_iterator)
        assert callable(process_in_batches)
        assert callable(chunked)
        assert callable(calculate_batch_stats)

    def test_import_from_batch(self):
        """Can import directly from batch module."""
        from data_platform.utils.batch import (
            batch_iterator,
            process_in_batches,
            chunked,
            calculate_batch_stats,
        )

        assert callable(batch_iterator)
        assert callable(process_in_batches)
        assert callable(chunked)
        assert callable(calculate_batch_stats)
