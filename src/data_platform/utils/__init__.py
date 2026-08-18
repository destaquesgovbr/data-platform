"""
Utility functions for data-platform.

This package contains shared utilities used across the codebase:
- datetime_utils: Date/time parsing and formatting
- batch: Batch processing utilities
"""

from data_platform.utils.batch import (
    batch_iterator,
    calculate_batch_stats,
    chunked,
    process_in_batches,
)
from data_platform.utils.datetime_utils import (
    calculate_published_week,
    parse_date,
    to_timestamp,
)

__all__ = [
    # Datetime utils
    "calculate_published_week",
    "parse_date",
    "to_timestamp",
    # Batch utils
    "batch_iterator",
    "process_in_batches",
    "chunked",
    "calculate_batch_stats",
]
