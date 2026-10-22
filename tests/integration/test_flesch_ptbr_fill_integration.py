"""
Integração da cobertura contínua do Flesch pt-BR (DP-1c) contra PostgreSQL real.

Valida a seleção por janela de updated_at (linhas sem a chave e com content), o merge no
JSONB que preserva as outras chaves, os textos curtos (sem chave) e a idempotência. Usa o
banco descartável de test_migrate_integration.py (MIGRATION_TEST_DATABASE_URL).
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from data_platform.jobs.features.flesch_ptbr_fill import run_fill_flesch_ptbr
from data_platform.jobs.features.readability_ptbr import compute_readability_flesch_ptbr
from tests.integration.test_migrate_integration import (
    DATABASE_URL,
    _apply_all_migrations,
    _execute,
    _reset_database,
)

LONGO = (
    "O Ministério da Educação anunciou hoje um novo programa nacional de apoio "
    "aos estudantes do ensino médio em todas as regiões do país."
)
CURTO = "Nota curta."
ENTITIES = [{"text": "Ministério da Educação", "type": "ORG", "canonical_id": "Q1"}]


def _news(unique_id: str, content: str) -> None:
    _execute(
        "INSERT INTO news (unique_id, agency_id, title, content, published_at, agency_key) "
        f"SELECT '{unique_id}', id, 'Título', '{content}', '2026-10-01T12:00:00+00:00', key "
        "FROM agencies WHERE key = 'mec'"
    )


def _features(unique_id: str, features: dict, updated_days_ago: int = 0) -> None:
    # O trigger de updated_at é BEFORE UPDATE: no INSERT o valor explícito vale.
    _execute(
        "INSERT INTO news_features (unique_id, features, updated_at) "
        f"VALUES ('{unique_id}', '{json.dumps(features, ensure_ascii=False)}'::jsonb, "
        f"now() - interval '{updated_days_ago} days')"
    )


def _features_of(unique_id: str) -> dict | None:
    rows = _execute(f"SELECT features FROM news_features WHERE unique_id = '{unique_id}'")
    return rows[0][0] if rows else None


@pytest.fixture(autouse=True)
def seeded_database():
    _reset_database()
    _apply_all_migrations()
    _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")
    _news("sem_chave", LONGO)
    _features("sem_chave", {"readability_flesch": 40.0, "entities": ENTITIES})
    _news("com_chave", LONGO)
    _features("com_chave", {"readability_flesch_ptbr": 12.34})
    _news("curto", CURTO)
    _features("curto", {"word_count": 2})
    _news("antigo", LONGO)
    _features("antigo", {"word_count": 22}, updated_days_ago=10)
    _news("sem_linha", LONGO)
    yield


@pytest.mark.integration
class TestFillFleschPtbr:
    def test_preenche_a_janela_e_preserva_as_outras_chaves(self):
        result = run_fill_flesch_ptbr(DATABASE_URL)

        assert result["scanned"] == 2  # sem_chave e curto
        assert result["updated"] == 1
        assert result["too_short"] == 1
        assert _features_of("sem_chave") == {
            "readability_flesch": 40.0,
            "entities": ENTITIES,
            "readability_flesch_ptbr": compute_readability_flesch_ptbr(LONGO),
        }
        assert _features_of("com_chave") == {"readability_flesch_ptbr": 12.34}
        assert _features_of("curto") == {"word_count": 2}
        assert _features_of("antigo") == {"word_count": 22}
        assert _features_of("sem_linha") is None

    def test_sem_janela_varre_tudo(self):
        result = run_fill_flesch_ptbr(DATABASE_URL, lookback_days=None)

        assert result["updated"] == 2
        assert "readability_flesch_ptbr" in _features_of("antigo")

    def test_idempotente(self):
        run_fill_flesch_ptbr(DATABASE_URL, lookback_days=None)
        again = run_fill_flesch_ptbr(DATABASE_URL, lookback_days=None)

        assert again["scanned"] == 1  # só o curto continua sem a chave
        assert again["updated"] == 0

    def test_dry_run_nao_grava(self):
        result = run_fill_flesch_ptbr(DATABASE_URL, dry_run=True)

        assert result["would_update"] == 1
        assert "readability_flesch_ptbr" not in _features_of("sem_chave")

    def test_janela_relativa_a_now(self):
        """Com `now` 20 dias no futuro, nenhuma linha entra na janela de 3 dias."""
        future = datetime.now(UTC) + timedelta(days=20)
        result = run_fill_flesch_ptbr(DATABASE_URL, now=future)

        assert result["scanned"] == 0
