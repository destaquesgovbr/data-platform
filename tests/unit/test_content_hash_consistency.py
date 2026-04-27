"""
Pinned reference vectors for content_hash consistency between repos.

These values MUST match scraper/tests/unit/test_content_hash.py::test_pinned_vectors.
If either side diverges, this test breaks before deploy.
"""

import importlib.util
import pathlib

import pytest

MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "scripts"
    / "migrations"
    / "010_backfill_content_hash.py"
)


@pytest.fixture
def hash_module():
    spec = importlib.util.spec_from_file_location("m010", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pinned_vectors_cross_repo(hash_module):
    assert hash_module.normalize_text("Educação Pública") == "educacao publica"
    assert hash_module.normalize_text("R$ 1 bilhão em 2025") == "r 1 bilhao em 2025"
    assert hash_module.compute_content_hash("Lula", "conteudo") == "7af6a8c98b1e027b"
    assert (
        hash_module.compute_content_hash("Governo anuncia programa", "Texto da notícia")
        == "ca58538e360baaf4"
    )


def test_empty_returns_none(hash_module):
    assert hash_module.compute_content_hash("", None) is None
    assert hash_module.compute_content_hash("", "") is None
