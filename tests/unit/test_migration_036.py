"""036_backfill_news_content_key.py: blocos cronológicos e projeção do dry-run (sem banco)."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "migrations"
    / "036_backfill_news_content_key.py"
)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_036", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fim_do_bloco(migration):
    assert migration.chunk_end(T0, T0 + timedelta(days=200), days=90) == T0 + timedelta(days=90)


def test_ultimo_bloco_fica_aberto(migration):
    """Sem `until`, o último bloco lê até o fim (artigos que chegam durante o backfill)."""
    assert migration.chunk_end(T0 + timedelta(days=180), T0 + timedelta(days=200), days=90) is None
    assert migration.chunk_end(T0, T0, days=90) is None


def test_blocos_de_90_dias(migration):
    assert migration.CHUNK_DAYS == 90


def test_projecao_linear_no_numero_de_artigos(migration):
    assert migration.project(sample_value=2.0, sample_size=4, total=100) == 50.0
    assert migration.project(sample_value=2.0, sample_size=0, total=100) == 0.0


def test_describe(migration):
    assert "content_key" in migration.describe()
