"""Cobertura contínua do Flesch pt-BR (DP-1c).

A 033 preencheu readability_flesch_ptbr nas linhas que existiam em news_features. Outros
escritores (enrichment_backfill, ner-backfill) criam ou reescrevem linhas sem a chave. A
tarefa diária fill_flesch_ptbr (DAG aggregate_engagement) relê as linhas tocadas nos
últimos dias que não têm a chave e grava o valor com merge no JSONB, como a 033.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.features import flesch_ptbr_fill as mod
from data_platform.jobs.features.readability_ptbr import compute_readability_flesch_ptbr

LONGO = (
    "O Ministério da Educação anunciou nesta segunda-feira um novo programa nacional de "
    "apoio aos estudantes do ensino médio em todas as regiões do país."
)
CURTO = "Nota curta sem frase completa."


class _Cursor:
    """Cursor falso: devolve os lotes em ordem e registra os SELECTs."""

    def __init__(self, batches: list[list[tuple[str, str]]]):
        self._batches = list(batches)
        self.selects: list[tuple[str, dict]] = []
        self.rowcount = 0
        self.closed = False

    def execute(self, sql, params=None):
        self.selects.append((sql, params))
        self._current = self._batches.pop(0) if self._batches else []

    def fetchall(self):
        return self._current

    def close(self):
        self.closed = True


def _set_rowcount(cursor, _sql, values, **_kwargs):
    """execute_values falso: o UPDATE grava todas as linhas do lote."""
    cursor.rowcount = len(values)


def _conn(batches):
    cursor = _Cursor(batches)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestSelecao:
    def test_janela_por_updated_at(self):
        sql = mod.build_select_pending(since=datetime(2026, 10, 19, tzinfo=UTC))
        assert "nf.updated_at >= %(since)s" in sql

    def test_sem_janela_varre_tudo(self):
        assert "updated_at" not in mod.build_select_pending(since=None)

    @pytest.mark.parametrize("since", [None, datetime(2026, 10, 19, tzinfo=UTC)])
    def test_filtros_da_033_e_keyset(self, since):
        sql = mod.build_select_pending(since=since)
        assert "JOIN news n ON n.unique_id = nf.unique_id" in sql
        assert "n.content IS NOT NULL" in sql
        assert "n.content <> ''" in sql
        assert "NOT (nf.features ? %(key)s)" in sql
        assert "nf.unique_id > %(after)s" in sql
        assert "ORDER BY nf.unique_id" in sql
        assert "LIMIT %(limit)s" in sql


class TestLote:
    def test_calcula_so_a_chave_nova(self):
        values, too_short = mod.build_batch([("a", LONGO)])
        assert too_short == 0
        assert values == [
            ("a", json.dumps({"readability_flesch_ptbr": compute_readability_flesch_ptbr(LONGO)}))
        ]

    def test_texto_curto_fica_de_fora(self):
        values, too_short = mod.build_batch([("a", CURTO), ("b", LONGO)])
        assert [uid for uid, _ in values] == ["b"]
        assert too_short == 1

    def test_update_faz_merge_e_nao_sobrescreve_a_chave(self):
        """Merge (||) preserva as outras chaves; a guarda evita regravar a chave que o
        feature-worker escreveu entre o SELECT e o UPDATE."""
        assert "features = nf.features || v.features" in mod.UPDATE_SQL
        assert "NOT (nf.features ? 'readability_flesch_ptbr')" in mod.UPDATE_SQL


class TestPreenchimento:
    def test_pagina_e_comita_por_lote(self):
        conn, cursor = _conn([[("a", LONGO), ("b", CURTO)], [("c", LONGO)]])
        since = datetime(2026, 10, 19, tzinfo=UTC)

        with patch.object(mod, "execute_values", side_effect=_set_rowcount) as ev:
            result = mod.fill_missing_flesch_ptbr(conn, since=since, batch_size=2)

        assert [params["after"] for _, params in cursor.selects] == ["", "b"]
        assert all(params["since"] == since for _, params in cursor.selects)
        assert all(params["key"] == "readability_flesch_ptbr" for _, params in cursor.selects)
        assert [[uid for uid, _ in call.args[2]] for call in ev.call_args_list] == [["a"], ["c"]]
        assert conn.commit.call_count == 2
        assert result["scanned"] == 3
        assert result["updated"] == 2
        assert result["too_short"] == 1
        assert result["exhausted"] is True
        assert cursor.closed

    def test_respeita_o_limite_da_execucao(self):
        conn, cursor = _conn([[("a", LONGO), ("b", LONGO)], [("c", LONGO)], [("d", LONGO)]])

        with patch.object(mod, "execute_values"):
            result = mod.fill_missing_flesch_ptbr(conn, since=None, limit=3, batch_size=2)

        assert [params["limit"] for _, params in cursor.selects] == [2, 1]
        assert result["scanned"] == 3
        assert result["exhausted"] is False

    def test_lote_so_de_curtos_nao_executa_update(self):
        conn, _ = _conn([[("a", CURTO)]])

        with patch.object(mod, "execute_values") as ev:
            result = mod.fill_missing_flesch_ptbr(conn, since=None, batch_size=2)

        ev.assert_not_called()
        assert result["updated"] == 0
        assert result["too_short"] == 1

    def test_dry_run_nao_grava(self):
        conn, _ = _conn([[("a", LONGO), ("b", CURTO)]])

        with patch.object(mod, "execute_values") as ev:
            result = mod.fill_missing_flesch_ptbr(conn, since=None, batch_size=5, dry_run=True)

        ev.assert_not_called()
        conn.commit.assert_not_called()
        assert result["updated"] == 0
        assert result["would_update"] == 1
        assert result["dry_run"] is True

    def test_sem_pendentes(self):
        conn, cursor = _conn([[]])

        with patch.object(mod, "execute_values") as ev:
            result = mod.fill_missing_flesch_ptbr(conn, since=None)

        ev.assert_not_called()
        assert len(cursor.selects) == 1
        assert result["scanned"] == 0
        assert result["exhausted"] is True


class TestTarefa:
    def test_janela_padrao_de_dias(self):
        now = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)
        conn = MagicMock()

        with (
            patch("psycopg2.connect", return_value=conn) as connect,
            patch.object(mod, "fill_missing_flesch_ptbr", return_value={"scanned": 0}) as fill,
        ):
            result = mod.run_fill_flesch_ptbr("postgresql://u@h/db", now=now)

        connect.assert_called_once_with("postgresql://u@h/db")
        assert conn.autocommit is False
        fill.assert_called_once_with(
            conn,
            since=now - timedelta(days=mod.LOOKBACK_DAYS),
            limit=mod.RUN_LIMIT,
            dry_run=False,
        )
        conn.close.assert_called_once()
        assert result == {"scanned": 0}

    def test_lookback_none_varre_tudo(self):
        conn = MagicMock()

        with (
            patch("psycopg2.connect", return_value=conn),
            patch.object(mod, "fill_missing_flesch_ptbr", return_value={}) as fill,
        ):
            mod.run_fill_flesch_ptbr("postgresql://u@h/db", lookback_days=None, limit=10)

        assert fill.call_args.kwargs["since"] is None
        assert fill.call_args.kwargs["limit"] == 10

    def test_erro_faz_rollback_e_fecha(self):
        conn = MagicMock()

        with (
            patch("psycopg2.connect", return_value=conn),
            patch.object(mod, "fill_missing_flesch_ptbr", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            mod.run_fill_flesch_ptbr("postgresql://u@h/db")

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_padroes_da_execucao_diaria(self):
        assert mod.LOOKBACK_DAYS == 3
        assert mod.RUN_LIMIT >= 10000
        assert mod.FEATURE_KEY == "readability_flesch_ptbr"
