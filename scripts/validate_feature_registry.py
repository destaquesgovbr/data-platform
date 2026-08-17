#!/usr/bin/env python3
"""Validate feature_registry.yaml schema and consistency."""

import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = {"version", "type", "description", "model", "compute"}
VALID_TYPES = {"integer", "float", "string", "boolean", "array", "object"}
VALID_COMPUTE = {"feature-worker", "enrichment-worker", "thumbnail-worker", "airflow-dag"}


def validate_feature(name: str, feature: dict[str, Any]) -> list[str]:
    """Validate a single feature definition."""
    errors = []

    # Check required fields
    missing = REQUIRED_FIELDS - set(feature.keys())
    if missing:
        errors.append(f"Feature '{name}' missing fields: {missing}")

    # Validate type
    if "type" in feature and feature["type"] not in VALID_TYPES:
        errors.append(f"Feature '{name}' has invalid type: {feature['type']}")

    # Validate compute
    if "compute" in feature and feature["compute"] not in VALID_COMPUTE:
        errors.append(f"Feature '{name}' has invalid compute: {feature['compute']}")

    return errors


def main() -> int:
    """Validate feature_registry.yaml."""
    file_path = Path("feature_registry.yaml")

    if not file_path.exists():
        print(f"ERROR: {file_path} not found")
        return 1

    try:
        with open(file_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML syntax: {e}")
        return 1

    if data is None:
        print("ERROR: Empty file or file contains only comments")
        return 1

    if "features" not in data:
        print("ERROR: Missing 'features' key")
        return 1

    errors = []
    for name, feature in data["features"].items():
        errors.extend(validate_feature(name, feature))

    if errors:
        print("\n".join(errors))
        return 1

    print(f"✓ Validated {len(data['features'])} features")
    return 0


if __name__ == "__main__":
    sys.exit(main())
