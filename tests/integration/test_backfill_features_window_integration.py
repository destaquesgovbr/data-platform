"""
Integração do scripts/backfill_features_window.py (B1) contra PostgreSQL real.

Valida a seleção (sem news_features, sem readability_flesch ou sem
content_annotations) e que uma passada completa grava as duas chaves com merge
no JSONB, deixando a seleção vazia (idempotente). Usa o banco descartável de
test_migrate_integration.py (MIGRATION_TEST_DATABASE_URL).
"""

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from tests.integration.test_migrate_integration import (
    DATABASE_URL,
    _apply_all_migrations,
    _execute,
    _reset_database,
)

SCRIPT = Path(__file__).parents[2] / "scripts" / "backfill_features_window.py"
CONTENT = (
    "O Ministério da Educação anunciou hoje um novo programa nacional de apoio "
    "aos estudantes do ensino médio em todas as regiões do país."
)
WINDOW = ["--date-from", "2026-05-20", "--date-to", "2026-10-09"]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("backfill_features_window", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _news(unique_id: str, published_at: str) -> None:
    _execute(
        "INSERT INTO news (unique_id, agency_id, title, content, published_at, agency_key) "
        f"SELECT '{unique_id}', id, 'Título', '{CONTENT}', '{published_at}', key "
        "FROM agencies WHERE key = 'mec'"
    )


def _features(unique_id: str, features: dict) -> None:
    _execute(
        "INSERT INTO news_features (unique_id, features) "
        f"VALUES ('{unique_id}', '{json.dumps(features, ensure_ascii=False)}'::jsonb)"
    )


ENTITIES = [{"text": "Ministério da Educação", "type": "ORG", "canonical_id": "Q1"}]


@pytest.fixture(autouse=True)
def seeded_database(monkeypatch):
    _reset_database()
    _apply_all_migrations()
    _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")
    _news("sem_linha", "2026-06-01T12:00:00+00:00")
    _news("so_flesch", "2026-07-01T12:00:00+00:00")
    _features(
        "so_flesch", {"readability_flesch": 40.0, "entities": ENTITIES, "sentiment": "neutro"}
    )
    _news("so_anotacoes", "2026-08-01T12:00:00+00:00")
    _features("so_anotacoes", {"content_annotations": []})
    _news("completo", "2026-09-01T12:00:00+00:00")
    _features("completo", {"readability_flesch": 40.0, "content_annotations": []})
    _news("fora_da_janela", "2026-04-01T12:00:00+00:00")
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    yield


def _select(mod) -> dict[str, tuple[bool, bool]]:
    rows = mod.select_articles(DATABASE_URL, date(2026, 5, 20), date(2026, 10, 9), 100)
    return {uid: (has_flesch, has_ann) for uid, has_flesch, has_ann in rows}


@pytest.mark.integration
class TestBackfillFeaturesWindow:
    def test_selecao_cobre_flesch_e_anotacoes(self, mod):
        assert _select(mod) == {
            "so_anotacoes": (False, True),
            "so_flesch": (True, False),
            "sem_linha": (False, False),
        }

    def test_dry_run_nao_grava(self, mod):
        assert mod.main([*WINDOW, "--dry-run"]) == 0

        assert len(_select(mod)) == 3
        assert _execute("SELECT count(*) FROM news_features") == [(3,)]

    def test_passada_completa_grava_e_esvazia_a_selecao(self, mod):
        assert mod.main(WINDOW) == 0

        assert _select(mod) == {}
        rows = _execute(
            "SELECT unique_id, features ? 'readability_flesch', "
            "features ? 'content_annotations', features ? 'word_count' "
            "FROM news_features WHERE unique_id IN ('sem_linha', 'so_flesch', 'so_anotacoes') "
            "ORDER BY unique_id"
        )
        assert rows == [
            ("sem_linha", True, True, True),
            ("so_anotacoes", True, True, True),
            ("so_flesch", True, True, True),
        ]

    def test_merge_preserva_chaves_e_deriva_anotacoes_das_entidades(self, mod):
        assert mod.main(WINDOW) == 0

        ((features,),) = _execute(
            "SELECT features FROM news_features WHERE unique_id = 'so_flesch'"
        )
        assert features["sentiment"] == "neutro"
        assert features["entities"] == ENTITIES
        assert features["content_annotations"] != []
        assert _execute(
            "SELECT count(*) FROM news_features WHERE unique_id = 'fora_da_janela'"
        ) == [(0,)]
