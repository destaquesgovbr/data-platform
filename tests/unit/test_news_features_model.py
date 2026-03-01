"""Unit tests for NewsFeatures Pydantic model."""

from datetime import datetime

from data_platform.models import NewsFeatures


class TestNewsFeatures:
    def test_create_minimal(self):
        nf = NewsFeatures(unique_id="abc123")
        assert nf.unique_id == "abc123"
        assert nf.features == {}
        assert nf.updated_at is None

    def test_create_with_features(self):
        nf = NewsFeatures(
            unique_id="abc123",
            features={"word_count": 150, "has_image": True},
            updated_at=datetime(2024, 1, 1),
        )
        assert nf.features["word_count"] == 150
        assert nf.features["has_image"] is True
