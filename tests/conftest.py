"""
Pytest configuration and fixtures.
"""

import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def set_test_environment():
    """Set testing environment variables."""
    os.environ["TESTING"] = "1"
    os.environ["STORAGE_BACKEND"] = "huggingface"  # Default for tests


@pytest.fixture
def sample_news_data():
    """Sample news data for testing."""
    from collections import OrderedDict

    return OrderedDict(
        [
            ("unique_id", ["abc123", "def456"]),
            ("agency", ["mec", "saude"]),
            ("title", ["Test News 1", "Test News 2"]),
            ("url", ["https://example.com/1", "https://example.com/2"]),
            ("content", ["Content 1", "Content 2"]),
            ("published_at", ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"]),
            ("extracted_at", ["2024-01-01T01:00:00Z", "2024-01-02T01:00:00Z"]),
        ]
    )
