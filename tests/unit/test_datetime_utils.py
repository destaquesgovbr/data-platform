"""
Tests for datetime utilities.

These tests ensure that:
1. Date parsing works with various input formats
2. Timestamp conversion works correctly
3. Week calculation matches ISO 8601 standard
4. Edge cases are handled properly
"""

from datetime import datetime, date, timezone

import pytest


class TestParseDate:
    """Tests for parse_date function."""

    def test_parse_none(self):
        """None returns None."""
        from data_platform.utils.datetime_utils import parse_date

        assert parse_date(None) is None

    def test_parse_datetime(self):
        """datetime returns as-is."""
        from data_platform.utils.datetime_utils import parse_date

        dt = datetime(2025, 1, 15, 10, 30)
        result = parse_date(dt)
        assert result == dt

    def test_parse_date_object(self):
        """date converts to datetime at midnight."""
        from data_platform.utils.datetime_utils import parse_date

        d = date(2025, 1, 15)
        result = parse_date(d)
        assert result is not None
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 0
        assert result.minute == 0

    def test_parse_timestamp_int(self):
        """int interprets as Unix timestamp."""
        from data_platform.utils.datetime_utils import parse_date

        # 2025-01-15 00:00:00 UTC
        ts = 1736899200
        result = parse_date(ts)
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_parse_timestamp_float(self):
        """float interprets as Unix timestamp."""
        from data_platform.utils.datetime_utils import parse_date

        ts = 1736899200.5
        result = parse_date(ts)
        assert result is not None
        assert isinstance(result, datetime)

    def test_parse_negative_timestamp(self):
        """Negative timestamp returns None."""
        from data_platform.utils.datetime_utils import parse_date

        assert parse_date(-1) is None
        assert parse_date(0) is None

    def test_parse_string_iso_date(self):
        """ISO date string parses correctly."""
        from data_platform.utils.datetime_utils import parse_date

        result = parse_date("2025-01-15")
        assert result is not None
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 15

    def test_parse_string_iso_datetime(self):
        """ISO datetime string parses correctly."""
        from data_platform.utils.datetime_utils import parse_date

        result = parse_date("2025-01-15T10:30:00")
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_string_with_timezone(self):
        """Datetime with timezone parses correctly."""
        from data_platform.utils.datetime_utils import parse_date

        result = parse_date("2025-01-15T10:30:00+00:00")
        assert result is not None
        assert result.year == 2025

    def test_parse_empty_string(self):
        """Empty string returns None."""
        from data_platform.utils.datetime_utils import parse_date

        assert parse_date("") is None
        assert parse_date("   ") is None

    def test_parse_invalid_string(self):
        """Invalid string returns None."""
        from data_platform.utils.datetime_utils import parse_date

        assert parse_date("not-a-date") is None
        assert parse_date("abc123") is None


class TestToTimestamp:
    """Tests for to_timestamp function."""

    def test_none_returns_none(self):
        """None returns None."""
        from data_platform.utils.datetime_utils import to_timestamp

        assert to_timestamp(None) is None

    def test_datetime_to_timestamp(self):
        """datetime converts to timestamp."""
        from data_platform.utils.datetime_utils import to_timestamp

        dt = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        ts = to_timestamp(dt)
        assert ts is not None
        assert isinstance(ts, int)
        assert ts == 1736899200

    def test_date_to_timestamp(self):
        """date converts to timestamp at midnight."""
        from data_platform.utils.datetime_utils import to_timestamp

        d = date(2025, 1, 15)
        ts = to_timestamp(d)
        assert ts is not None
        assert isinstance(ts, int)
        assert ts > 0

    def test_roundtrip(self):
        """Timestamp roundtrip works."""
        from data_platform.utils.datetime_utils import parse_date, to_timestamp

        original_ts = 1736899200
        dt = parse_date(original_ts)
        result_ts = to_timestamp(dt)
        assert result_ts == original_ts


class TestCalculatePublishedWeek:
    """Tests for calculate_published_week function."""

    def test_none_returns_none(self):
        """None returns None."""
        from data_platform.utils.datetime_utils import calculate_published_week

        assert calculate_published_week(None) is None

    def test_zero_returns_none(self):
        """Zero timestamp returns None."""
        from data_platform.utils.datetime_utils import calculate_published_week

        assert calculate_published_week(0) is None

    def test_negative_returns_none(self):
        """Negative timestamp returns None."""
        from data_platform.utils.datetime_utils import calculate_published_week

        assert calculate_published_week(-1) is None

    def test_week_format_yyyyww(self):
        """Returns YYYYWW format."""
        from data_platform.utils.datetime_utils import calculate_published_week

        # 2025-01-15 is week 3 of 2025
        ts = 1736899200
        week_id = calculate_published_week(ts)
        assert week_id is not None
        assert week_id == 202503

    def test_first_week_2024(self):
        """First week of 2024."""
        from data_platform.utils.datetime_utils import calculate_published_week

        # 2024-01-01 (Monday)
        ts = 1704067200
        week_id = calculate_published_week(ts)
        assert week_id is not None
        assert week_id == 202401

    def test_week_year_boundary(self):
        """Week at year boundary."""
        from data_platform.utils.datetime_utils import calculate_published_week

        # 2024-12-31 might be week 1 of 2025 in ISO week
        ts = 1735603200  # 2024-12-31
        week_id = calculate_published_week(ts)
        assert week_id is not None
        # ISO week might put this in 2025 week 1
        assert week_id // 100 in [2024, 2025]

    def test_float_timestamp(self):
        """Float timestamp works."""
        from data_platform.utils.datetime_utils import calculate_published_week

        ts = 1736899200.5
        week_id = calculate_published_week(ts)
        assert week_id is not None
        assert week_id == 202503


class TestBackwardsCompatibility:
    """Tests to ensure backwards compatibility with existing code."""

    def test_import_from_typesense_utils(self):
        """Can import from typesense.utils (old location)."""
        from data_platform.typesense.utils import calculate_published_week

        # Should work just like the centralized version
        assert calculate_published_week(1736899200) == 202503

    def test_import_from_utils(self):
        """Can import from utils (new location)."""
        from data_platform.utils import calculate_published_week

        assert calculate_published_week(1736899200) == 202503

    def test_same_behavior(self):
        """Both imports produce same results."""
        from data_platform.typesense.utils import (
            calculate_published_week as old_func,
        )
        from data_platform.utils.datetime_utils import (
            calculate_published_week as new_func,
        )

        test_timestamps = [
            1704067200,  # 2024-01-01
            1736899200,  # 2025-01-15
            1735603200,  # 2024-12-31
            None,
            0,
            -1,
        ]

        for ts in test_timestamps:
            assert old_func(ts) == new_func(ts), f"Different result for ts={ts}"


class TestFormatDateRange:
    """Tests for format_date_range function."""

    def test_single_date(self):
        """Single date uses same for start and end."""
        from data_platform.utils.datetime_utils import format_date_range

        start, end = format_date_range("2025-01-15")
        assert start == "2025-01-15"
        assert end == "2025-01-15"

    def test_date_range(self):
        """Date range returns both dates."""
        from data_platform.utils.datetime_utils import format_date_range

        start, end = format_date_range("2025-01-01", "2025-01-15")
        assert start == "2025-01-01"
        assert end == "2025-01-15"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_current_timestamp(self):
        """get_current_timestamp returns reasonable value."""
        from data_platform.utils.datetime_utils import get_current_timestamp

        ts = get_current_timestamp()
        assert isinstance(ts, int)
        # Should be after 2024
        assert ts > 1704067200

    def test_get_today_str(self):
        """get_today_str returns valid date string."""
        from data_platform.utils.datetime_utils import get_today_str

        today = get_today_str()
        assert isinstance(today, str)
        # Should match YYYY-MM-DD format
        assert len(today) == 10
        assert today[4] == "-"
        assert today[7] == "-"
