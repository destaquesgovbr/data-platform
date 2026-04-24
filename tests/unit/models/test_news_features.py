"""Unit tests for NewsFeatures Pydantic model."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

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

    def test_serialization_to_dict(self):
        nf = NewsFeatures(unique_id="abc123", features={"score": 0.9})
        data = nf.model_dump()
        assert data["unique_id"] == "abc123"
        assert data["features"] == {"score": 0.9}
        assert "updated_at" in data

    def test_updated_at_timezone_aware(self):
        dt = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        nf = NewsFeatures(unique_id="abc123", updated_at=dt)
        assert nf.updated_at == dt

    def test_nested_features_dict(self):
        """features can hold nested dicts (e.g. sentiment sub-object)."""
        nf = NewsFeatures(
            unique_id="abc123",
            features={"sentiment": {"label": "positive", "score": 0.85}},
        )
        assert nf.features["sentiment"]["label"] == "positive"

    def test_unique_id_required(self):
        with pytest.raises(ValidationError):
            NewsFeatures()
