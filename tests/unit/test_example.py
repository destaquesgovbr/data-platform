"""
Example tests to validate setup.
"""

import os
import pytest


def test_environment_is_set():
    """Test that TESTING environment variable is set."""
    assert os.getenv("TESTING") == "1"


def test_sample_data_fixture(sample_news_data):
    """Test that sample data fixture works."""
    assert "unique_id" in sample_news_data
    assert len(sample_news_data["unique_id"]) == 2
    assert sample_news_data["unique_id"][0] == "abc123"


def test_basic_import():
    """Test that package can be imported."""
    import data_platform

    assert data_platform is not None


@pytest.mark.parametrize(
    "agency,expected",
    [
        ("mec", "Ministério da Educação"),
        ("saude", "Ministério da Saúde"),
    ],
)
def test_parametrized_example(agency, expected):
    """Example of parametrized test."""
    # This is just an example - actual implementation would lookup agency name
    agency_names = {
        "mec": "Ministério da Educação",
        "saude": "Ministério da Saúde",
    }
    assert agency_names.get(agency) == expected
