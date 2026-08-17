"""Tests for scripts/validate_feature_registry.py CLI behavior."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


@pytest.fixture
def tmp_registry(tmp_path):
    """Fixture to create a temporary feature_registry.yaml file."""
    registry_path = tmp_path / "feature_registry.yaml"
    original_cwd = Path.cwd()

    def _create_registry(content: str):
        registry_path.write_text(content)
        return tmp_path

    yield _create_registry

    # Cleanup: restore original directory
    import os

    os.chdir(original_cwd)


def test_validator_empty_file(tmp_registry, capsys):
    """Empty file should return exit code 1 with appropriate error message."""
    registry_dir = tmp_registry("")

    # Change to temp directory and run validator
    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR: Empty file or file contains only comments" in captured.out


def test_validator_file_with_only_comments(tmp_registry, capsys):
    """File with only comments should return exit code 1."""
    registry_dir = tmp_registry("# This is a comment\n# Another comment\n")

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR: Empty file or file contains only comments" in captured.out


def test_validator_missing_features_key(tmp_registry, capsys):
    """File without 'features' key should fail."""
    registry_dir = tmp_registry("version: 1.0\nother_key: value\n")

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR: Missing 'features' key" in captured.out


def test_validator_invalid_yaml(tmp_registry, capsys):
    """File with invalid YAML syntax should fail."""
    registry_dir = tmp_registry("features:\n  - invalid: [unclosed bracket\n")

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR: Invalid YAML syntax" in captured.out


def test_validator_missing_required_fields(tmp_registry, capsys):
    """Feature missing required fields should fail."""
    content = """
features:
  test_feature:
    version: "1.0"
    type: string
    # Missing: description, model, compute
"""
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing fields" in captured.out
    assert "test_feature" in captured.out


def test_validator_invalid_type(tmp_registry, capsys):
    """Feature with invalid type should fail."""
    content = """
features:
  test_feature:
    version: "1.0"
    type: invalid_type
    description: Test
    model: none
    compute: feature-worker
"""
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid type" in captured.out
    assert "invalid_type" in captured.out


def test_validator_invalid_compute(tmp_registry, capsys):
    """Feature with invalid compute value should fail."""
    content = """
features:
  test_feature:
    version: "1.0"
    type: string
    description: Test
    model: none
    compute: invalid-worker
"""
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid compute" in captured.out
    assert "invalid-worker" in captured.out


def test_validator_valid_file(tmp_registry, capsys):
    """Valid file should return exit code 0 and success message."""
    content = """
features:
  test_feature:
    version: "1.0"
    type: string
    description: Test feature for unit testing
    model: none
    compute: feature-worker
  another_feature:
    version: "1.0"
    type: integer
    description: Another test feature
    model: none
    compute: airflow-dag
"""
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "✓ Validated 2 features" in captured.out


def test_validator_all_valid_compute_values(tmp_registry, capsys):
    """Test that all valid compute values are accepted."""
    valid_computes = ["feature-worker", "enrichment-worker", "thumbnail-worker", "airflow-dag"]

    features = {}
    for i, compute in enumerate(valid_computes):
        features[f"feature_{i}"] = {
            "version": "1.0",
            "type": "string",
            "description": f"Test feature with {compute}",
            "model": "none",
            "compute": compute,
        }

    content = yaml.dump({"features": features})
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "✓ Validated 4 features" in captured.out


def test_validator_all_valid_types(tmp_registry, capsys):
    """Test that all valid types are accepted."""
    valid_types = ["integer", "float", "string", "boolean", "array", "object"]

    features = {}
    for i, feature_type in enumerate(valid_types):
        features[f"feature_{i}"] = {
            "version": "1.0",
            "type": feature_type,
            "description": f"Test feature with type {feature_type}",
            "model": "none",
            "compute": "feature-worker",
        }

    content = yaml.dump({"features": features})
    registry_dir = tmp_registry(content)

    import os

    os.chdir(registry_dir)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "✓ Validated 6 features" in captured.out


def test_validator_file_not_found(tmp_path, capsys):
    """Non-existent file should return exit code 1."""
    import os

    os.chdir(tmp_path)

    from scripts.validate_feature_registry import main

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR:" in captured.out
    assert "not found" in captured.out
