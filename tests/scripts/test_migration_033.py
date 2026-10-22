"""Unit tests for scripts/migrations/033_backfill_readability_flesch_ptbr.py.

Cobre as partes puras (SQL de seleção/gravação, montagem do lote, projeção do
dry-run) e a orquestração de migrate/rollback com cursor mockado. A integração
contra PostgreSQL real fica em tests/integration/test_migrate_integration.py.
"""

import importlib.util
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data_platform.workers.feature_worker.features import compute_readability_flesch_ptbr

LONG = (
    "O Ministério da Educação anunciou nesta segunda-feira a ampliação do "
    "programa de bolsas para estudantes de baixa renda em todo o país."
)


def _import_migration_033():
    """Import the migration module dynamically (numeric prefix not importable directly)."""
    module_path = (
        Path(__file__).parent.parent.parent
        / "scripts"
        / "migrations"
        / "033_backfill_readability_flesch_ptbr.py"
    )
    spec = importlib.util.spec_from_file_location("migration_033", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def _conn_with_cursor():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------
class TestMigration033Interface:
    def test_describe_returns_nonempty_string(self):
        mod = _import_migration_033()
        assert isinstance(mod.describe(), str)
        assert mod.describe()

    def test_has_migrate_and_rollback(self):
        mod = _import_migration_033()
        assert callable(getattr(mod, "migrate", None))
        assert callable(getattr(mod, "rollback", None))

    def test_parametros_do_backfill(self):
        mod = _import_migration_033()
        assert mod.FEATURE_KEY == "readability_flesch_ptbr"
        assert mod.BATCH_SIZE == 2000
        assert mod.SAMPLE_SIZE == 1000


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
class TestSelectionSQL:
    def test_keyset_pela_pk_de_news_features(self):
        norm = _normalize(_import_migration_033().SELECT_PENDING_SQL)
        assert "nf.unique_id > %(after)s" in norm
        assert norm.endswith("order by nf.unique_id limit %(limit)s")

    def test_so_linhas_existentes_de_news_features_com_content_e_sem_a_chave(self):
        """Só UPDATE: parte de news_features (INNER JOIN com news), nunca de news.

        Notícias sem linha em news_features (~153,8 mil, quase todas pré-2022) ficam de
        fora por decisão. Retomável: quem já tem a chave (do backfill ou do
        feature-worker) é pulado."""
        mod = _import_migration_033()
        for sql in (mod.SELECT_PENDING_SQL, mod.COUNT_PENDING_SQL):
            norm = _normalize(sql)
            assert "from news_features nf join news n on n.unique_id = nf.unique_id" in norm
            assert "left join" not in norm
            assert "n.content is not null" in norm
            assert "n.content <> ''" in norm
            assert "not (nf.features ? %(key)s)" in norm

    def test_select_traz_unique_id_e_content(self):
        norm = _normalize(_import_migration_033().SELECT_PENDING_SQL)
        assert norm.startswith("select nf.unique_id, n.content from news_features nf")


class TestUpdateSQL:
    def test_merge_jsonb_por_lote_com_execute_values_sem_insert(self):
        mod = _import_migration_033()
        norm = _normalize(mod.UPDATE_SQL)
        assert norm == (
            "update news_features as nf set features = nf.features || v.features "
            "from (values %s) as v (unique_id, features) "
            "where nf.unique_id = v.unique_id"
        )
        assert "insert" not in norm
        assert mod.UPDATE_TEMPLATE == "(%s, %s::jsonb)"

    def test_nao_ha_mais_upsert(self):
        mod = _import_migration_033()
        assert not hasattr(mod, "UPSERT_SQL")
        assert not hasattr(mod, "UPSERT_TEMPLATE")


class TestRollbackSQL:
    def test_remove_so_a_chave_em_lotes(self):
        norm = _normalize(_import_migration_033().ROLLBACK_BATCH_SQL)
        assert "update news_features set features = features - %(key)s" in norm
        assert "where features ? %(key)s limit %(limit)s" in norm


# ---------------------------------------------------------------------------
# Lote e projeção
# ---------------------------------------------------------------------------
class TestBuildBatch:
    def test_calcula_com_a_funcao_do_feature_worker(self):
        mod = _import_migration_033()
        values, too_short = mod.build_batch([("a", LONG)])

        assert too_short == 0
        assert len(values) == 1
        uid, payload = values[0]
        assert uid == "a"
        assert json.loads(payload) == {
            "readability_flesch_ptbr": compute_readability_flesch_ptbr(LONG)
        }

    def test_texto_curto_nao_grava_e_e_contado(self):
        mod = _import_migration_033()
        values, too_short = mod.build_batch([("a", LONG), ("b", "Curto demais."), ("c", LONG)])

        assert [uid for uid, _ in values] == ["a", "c"]
        assert too_short == 1

    def test_lote_vazio(self):
        assert _import_migration_033().build_batch([]) == ([], 0)


class TestProjectSeconds:
    def test_projecao_linear_pela_amostra(self):
        mod = _import_migration_033()
        assert mod.project_seconds(2.0, 1000, 300_000) == pytest.approx(600.0)

    def test_amostra_vazia_projeta_zero(self):
        assert _import_migration_033().project_seconds(0.0, 0, 300_000) == 0.0

    def test_nada_pendente_projeta_zero(self):
        assert _import_migration_033().project_seconds(1.5, 1000, 0) == 0.0


# ---------------------------------------------------------------------------
# migrate / rollback com cursor mockado
# ---------------------------------------------------------------------------
class TestMigrateDryRun:
    def test_conta_pendentes_e_cronometra_amostra_sem_gravar(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (4001,)
        cursor.fetchall.return_value = [("a", LONG), ("b", "Curto.")]

        with patch.object(mod, "execute_values") as ev:
            result = mod.migrate(conn, dry_run=True)

        ev.assert_not_called()
        conn.commit.assert_not_called()
        sample_call = cursor.execute.call_args_list[1]
        assert sample_call.args[0] == mod.SELECT_PENDING_SQL
        assert sample_call.args[1] == {"key": mod.FEATURE_KEY, "after": "", "limit": 1000}
        assert result["preview"] is True
        assert result["pending"] == 4001
        assert result["batches"] == 3
        assert result["sample_size"] == 2
        assert result["sample_too_short"] == 1
        assert result["sample_compute_seconds"] >= 0
        assert result["projected_compute_seconds"] >= 0

    def test_projecao_vai_para_o_log(self):
        """O runner grava o dict do dry-run no migration_history e dá rollback: só o log
        do workflow db-migrate mostra a projeção."""
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (10,)
        cursor.fetchall.return_value = [("a", LONG)]

        with patch.object(mod, "logger") as log:
            result = mod.migrate(conn, dry_run=True)

        logged = " ".join(str(c.args[0]) for c in log.info.call_args_list)
        assert "pending=10" in logged
        assert f"projected_compute_seconds={result['projected_compute_seconds']}" in logged


class TestMigrateExecution:
    def test_pagina_por_unique_id_e_commita_por_lote(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (3,)
        cursor.fetchall.side_effect = [[("a", LONG), ("b", "Curto.")], [("c", LONG)], []]

        with patch.object(mod, "execute_values") as ev:
            result = mod.migrate(conn, dry_run=False)

        selects = [
            c.args[1] for c in cursor.execute.call_args_list if c.args[0] == mod.SELECT_PENDING_SQL
        ]
        assert [s["after"] for s in selects] == ["", "b", "c"]
        assert all(s["limit"] == 2000 for s in selects)
        assert ev.call_count == 2
        first_values = ev.call_args_list[0].args[2]
        assert [uid for uid, _ in first_values] == ["a"]
        assert ev.call_args_list[0].args[1] == mod.UPDATE_SQL
        assert ev.call_args_list[0].kwargs["template"] == mod.UPDATE_TEMPLATE
        assert conn.commit.call_count == 2
        assert result["rows_updated"] == 2
        assert result["too_short"] == 1
        assert result["scanned"] == 3

    def test_lote_so_com_textos_curtos_nao_chama_execute_values(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (1,)
        cursor.fetchall.side_effect = [[("b", "Curto.")], []]

        with patch.object(mod, "execute_values") as ev:
            result = mod.migrate(conn, dry_run=False)

        ev.assert_not_called()
        assert result["rows_updated"] == 0
        assert result["too_short"] == 1

    def test_nada_pendente(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (0,)

        with patch.object(mod, "execute_values") as ev:
            result = mod.migrate(conn, dry_run=False)

        ev.assert_not_called()
        assert result["rows_updated"] == 0
        assert cursor.execute.call_count == 1


class TestRollback:
    def test_dry_run_so_conta(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (2500,)

        result = mod.rollback(conn, dry_run=True)

        assert result == {"rows_cleared": 0, "to_clear": 2500, "preview": True}
        conn.commit.assert_not_called()

    def test_remove_em_lotes_ate_esgotar(self):
        mod = _import_migration_033()
        conn, cursor = _conn_with_cursor()
        cursor.fetchone.return_value = (2500,)
        rowcounts = iter([2000, 500, 0])

        def execute(sql, params=None):
            cursor.rowcount = next(rowcounts) if sql == mod.ROLLBACK_BATCH_SQL else -1

        cursor.execute.side_effect = execute

        result = mod.rollback(conn, dry_run=False)

        assert result == {"rows_cleared": 2500}
        assert conn.commit.call_count == 2
        batch_params = [
            c.args[1] for c in cursor.execute.call_args_list if c.args[0] == mod.ROLLBACK_BATCH_SQL
        ]
        assert batch_params[0] == {"key": "readability_flesch_ptbr", "limit": 2000}
