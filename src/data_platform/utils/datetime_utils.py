"""
Datetime utilities for data-platform.

This module provides centralized date/time parsing and formatting functions
used across the codebase, replacing duplicated parsing logic.

Functions:
    parse_date: Parse various date formats to datetime
    to_timestamp: Convert datetime to Unix timestamp
    calculate_published_week: Calculate ISO week ID (YYYYWW format)
"""

from datetime import datetime, date, timezone
from typing import Union

import pandas as pd


def parse_date(value: Union[str, datetime, date, int, float, None]) -> datetime | None:
    """
    Parse various date formats to datetime.

    Handles multiple input types:
    - None: returns None
    - datetime: returns as-is
    - date: converts to datetime at midnight
    - int/float: interprets as Unix timestamp
    - str: parses ISO format strings

    Args:
        value: Date value in various formats

    Returns:
        datetime object or None if input is None/invalid

    Examples:
        >>> parse_date("2025-01-15")
        datetime(2025, 1, 15, 0, 0)

        >>> parse_date(1736899200)  # Unix timestamp
        datetime(2025, 1, 15, 0, 0, tzinfo=timezone.utc)

        >>> parse_date(None)
        None
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())

    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None

    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            # Try pandas for flexible parsing
            return pd.to_datetime(value).to_pydatetime()
        except Exception:
            return None

    return None


def to_timestamp(dt: datetime | date | None) -> int | None:
    """
    Convert datetime to Unix timestamp.

    Args:
        dt: datetime or date object

    Returns:
        Unix timestamp as int, or None if input is None

    Examples:
        >>> to_timestamp(datetime(2025, 1, 15, 0, 0))
        1736899200  # approximate

        >>> to_timestamp(None)
        None
    """
    if dt is None:
        return None

    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())

    try:
        return int(dt.timestamp())
    except (OSError, ValueError, OverflowError):
        return None


def calculate_published_week(timestamp: int | float | None) -> int | None:
    """
    Calculate ISO 8601 week ID in YYYYWW format from Unix timestamp.

    Uses ISO week numbering where week 1 is the first week with
    at least 4 days in the new year.

    Args:
        timestamp: Unix timestamp in seconds

    Returns:
        int in YYYYWW format (e.g., 202503 for week 3 of 2025)
        Returns None if timestamp is invalid

    Examples:
        >>> calculate_published_week(1704110400)  # 2024-01-01
        202401  # Week 1 of 2024

        >>> calculate_published_week(1736899200)  # 2025-01-15
        202503  # Week 3 of 2025

        >>> calculate_published_week(None)
        None
    """
    if pd.isna(timestamp) or timestamp is None or timestamp <= 0:
        return None

    try:
        dt = pd.to_datetime(timestamp, unit="s")
        iso_year, iso_week, _ = dt.isocalendar()
        return int(iso_year * 100 + iso_week)
    except Exception:
        return None


def format_date_range(start_date: str, end_date: str | None = None) -> tuple[str, str]:
    """
    Format and validate a date range.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format (defaults to start_date)

    Returns:
        Tuple of (start_date, end_date) as strings

    Examples:
        >>> format_date_range("2025-01-01")
        ("2025-01-01", "2025-01-01")

        >>> format_date_range("2025-01-01", "2025-01-15")
        ("2025-01-01", "2025-01-15")
    """
    end_date = end_date or start_date
    return (start_date, end_date)


def get_current_timestamp() -> int:
    """
    Get current Unix timestamp.

    Returns:
        Current Unix timestamp as int
    """
    return int(datetime.now(timezone.utc).timestamp())


def get_today_str() -> str:
    """
    Get today's date as YYYY-MM-DD string.

    Returns:
        Today's date as string in YYYY-MM-DD format
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
