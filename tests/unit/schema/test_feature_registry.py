"""
Unit tests for Feature Registry YAML.

Validates the feature_registry.yaml file structure and completeness.
"""

from pathlib import Path

import pytest
import yaml

REGISTRY_PATH = Path(__file__).parent.parent.parent.parent / "feature_registry.yaml"

VALID_TYPES = {"integer", "float", "boolean", "string", "object", "array"}
REQUIRED_KEYS = {"version", "type", "description", "model", "compute"}


@pytest.fixture(scope="module")
def registry():
    """Load the feature registry."""
    assert REGISTRY_PATH.exists(), f"feature_registry.yaml not found at {REGISTRY_PATH}"
    with open(REGISTRY_PATH) as f:
        return yaml.safe_load(f)


class TestFeatureRegistry:
    """Tests for feature_registry.yaml."""

    def test_registry_has_features(self, registry):
        """Registry has a 'features' key with at least one entry."""
        assert "features" in registry
        assert len(registry["features"]) > 0

    def test_each_feature_has_required_keys(self, registry):
        """Every feature must have version, type, description, model, compute."""
        for name, spec in registry["features"].items():
            missing = REQUIRED_KEYS - set(spec.keys())
            assert not missing, f"Feature '{name}' missing keys: {missing}"

    def test_each_feature_has_valid_type(self, registry):
        """Every feature type must be one of the valid types."""
        for name, spec in registry["features"].items():
            assert spec["type"] in VALID_TYPES, (
                f"Feature '{name}' has invalid type '{spec['type']}'. "
                f"Valid types: {VALID_TYPES}"
            )

    def test_versions_are_strings(self, registry):
        """All versions must be strings (e.g., '1.0', not 1.0)."""
        for name, spec in registry["features"].items():
            assert isinstance(spec["version"], str), (
                f"Feature '{name}' version must be a string, got {type(spec['version'])}"
            )

    def test_expected_local_features_exist(self, registry):
        """Phase 1 local features must all be present."""
        expected = {
            "word_count",
            "char_count",
            "paragraph_count",
            "has_image",
            "has_video",
            "publication_hour",
            "publication_dow",
            "readability_flesch",
        }
        actual = set(registry["features"].keys())
        missing = expected - actual
        assert not missing, f"Missing local features: {missing}"

    def test_expected_ai_features_exist(self, registry):
        """Phase 1 AI features must all be present."""
        expected = {"sentiment", "entities"}
        actual = set(registry["features"].keys())
        missing = expected - actual
        assert not missing, f"Missing AI features: {missing}"
