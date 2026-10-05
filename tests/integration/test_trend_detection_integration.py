"""
Integração do trend detection (signals + persist) contra PostgreSQL real.

Aplica todas as migrações (inclusive a 029) num banco descartável e valida o SQL
que os testes unitários só exercitam com mocks: contagem de dias ativos em BRT,
override de baseline (D2) e o snapshot único gravado pelo persist.

Requer: PostgreSQL com pgvector, apontado por MIGRATION_TEST_DATABASE_URL (o mesmo
banco descartável de test_migrate_integration.py; ver ci-migrations.yaml):
    pytest tests/integration/test_trend_detection_integration.py --no-cov
"""

from datetime import date

import pytest

from data_platform.jobs.trend_detection.persist import upsert_trending_scores
from data_platform.jobs.trend_detection.signals import load_snapshot
from tests.integration.test_migrate_integration import (
    DATABASE_URL,
    _apply_all_migrations,
    _execute,
    _reset_database,
)


@pytest.fixture(autouse=True)
def migrated_database():
    _reset_database()
    _apply_all_migrations()
    _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC'), ('mds', 'MDS')")
    yield


def _insert_article(unique_id: str, agency_key: str, published_at: str, entity_id: str) -> None:
    _execute(
        "INSERT INTO news (unique_id, agency_id, title, published_at, agency_key) "
        f"SELECT '{unique_id}', id, 'Título', '{published_at}', key "
        f"FROM agencies WHERE key = '{agency_key}'"
    )
    _execute(
        "INSERT INTO news_entities (unique_id, entity_id, type, published_at) "
        f"VALUES ('{unique_id}', '{entity_id}', 'ORG', '{published_at}')"
    )


def _insert_entity(entity_id: str, name: str = "Entidade") -> None:
    _execute(
        "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance) "
        f"VALUES ('{entity_id}', '{name}', 'ORG', 'llm')"
    )


@pytest.mark.integration
class TestLoadSnapshotSql:
    def test_conta_dias_ativos_no_fuso_de_sao_paulo(self):
        """02h UTC de 01/10 é 23h de 30/09 em BRT: 3 artigos, 1 dia UTC, 2 dias BRT."""
        _insert_entity("Q_brt")
        _insert_article("a1", "mec", "2026-10-01T02:00:00+00:00", "Q_brt")
        _insert_article("a2", "mds", "2026-10-01T12:00:00+00:00", "Q_brt")
        _insert_article("a3", "mec", "2026-10-01T20:00:00+00:00", "Q_brt")

        data = load_snapshot(DATABASE_URL, date_end=date(2026, 10, 5))

        s = data["entity_stats"]["Q_brt"]
        assert s["window_count"] == 3
        assert s["window_agencies"] == 2
        assert s["window_active_days"] == 2
        assert s["baseline_count"] == 0
        assert s["is_new"] is True
        assert s["volume_ratio"] == pytest.approx(16.0)

    def test_override_de_baseline_conta_artigos_pre_defeso(self):
        _insert_entity("Q_junho")
        for i, day in enumerate(["2026-10-20", "2026-10-21", "2026-10-22"]):
            _insert_article(f"w{i}", "mec", f"{day}T15:00:00+00:00", "Q_junho")
        _insert_article("b1", "mec", "2026-06-10T15:00:00+00:00", "Q_junho")

        rolante = load_snapshot(DATABASE_URL, date_end=date(2026, 10, 26))
        override = load_snapshot(
            DATABASE_URL,
            date_end=date(2026, 10, 26),
            baseline_start=date(2026, 6, 6),
            baseline_end=date(2026, 7, 4),
        )

        assert rolante["entity_stats"]["Q_junho"]["baseline_count"] == 0
        assert override["entity_stats"]["Q_junho"]["baseline_count"] == 1
        assert override["entity_stats"]["Q_junho"]["is_new"] is False
        assert override["entity_stats"]["Q_junho"]["volume_ratio"] == pytest.approx(8.0)


def _stats(name: str, **overrides) -> dict:
    s = {
        "canonical_name": name,
        "entity_type": "ORG",
        "window_count": 3,
        "baseline_count": 0,
        "window_daily": 3 / 7,
        "baseline_daily": 0.0,
        "volume_ratio": 16.0,
        "is_new": True,
        "window_active_days": 2,
        "window_agencies": 2,
        "baseline_agencies": 0,
        "semantic_novelty": 0.0,
        "new_edge_count": 0,
    }
    s.update(overrides)
    return s


def _insert_stale_score(entity_id: str) -> None:
    _execute(
        "INSERT INTO entity_trending_scores (entity_id, canonical_name, type, trending_score, "
        "volume_ratio, window_count, window_agencies, computed_at) "
        f"VALUES ('{entity_id}', 'Velha', 'ORG', 99.0, 8571.0, 3, 2, NOW() - INTERVAL '6 hours')"
    )


@pytest.mark.integration
class TestPersistSnapshotSql:
    def test_substitui_execucao_anterior_e_grava_baseline(self):
        _insert_stale_score("Q_velho")

        count = upsert_trending_scores(
            DATABASE_URL,
            [("Q_novo", 9.0)],
            {"Q_novo": _stats("Nova", baseline_count=2, baseline_agencies=1, volume_ratio=4.0)},
        )

        assert count == 1
        rows = _execute(
            "SELECT entity_id, volume_ratio, baseline_count, baseline_agencies "
            "FROM entity_trending_scores"
        )
        assert rows == [("Q_novo", 4.0, 2, 1)]

    def test_reexecucao_mantem_um_unico_computed_at(self):
        stats = {"Q1": _stats("Um"), "Q2": _stats("Dois")}
        upsert_trending_scores(DATABASE_URL, [("Q1", 5.0), ("Q2", 4.0)], stats)
        upsert_trending_scores(DATABASE_URL, [("Q1", 6.0)], stats)

        rows = _execute(
            "SELECT count(*), count(DISTINCT computed_at), max(trending_score) "
            "FROM entity_trending_scores"
        )
        assert rows == [(1, 1, 6.0)]

    def test_sem_stats_preserva_snapshot(self):
        _insert_stale_score("Q_velho")

        assert upsert_trending_scores(DATABASE_URL, [], {}) == 0

        assert _execute("SELECT entity_id FROM entity_trending_scores") == [("Q_velho",)]

    def test_scores_vazios_com_stats_esvaziam_snapshot(self):
        _insert_stale_score("Q_velho")

        assert upsert_trending_scores(DATABASE_URL, [], {"Q1": _stats("Um")}) == 0

        assert _execute("SELECT count(*) FROM entity_trending_scores") == [(0,)]
