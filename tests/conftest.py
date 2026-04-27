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
