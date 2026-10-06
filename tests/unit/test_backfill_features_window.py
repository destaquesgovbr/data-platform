"""Testes unitarios de scripts/backfill_features_window.py (backfill B1, Fase 2.5)."""

import importlib.util
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "backfill_features_window.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("backfill_features_window", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(mod) -> str:
    return " ".join(mod.SELECT_SQL.split())


class TestArgumentos:
    def test_date_to_padrao_e_amanha(self, mod):
        args = mod.parse_args(["--date-from", "2026-05-20"])
        assert args.date_from == date(2026, 5, 20)
        assert args.date_to == date.today() + timedelta(days=1)
        assert args.dry_run is False

    def test_date_to_explicito_e_dry_run(self, mod):
        args = mod.parse_args(
            ["--date-from", "2026-05-20", "--date-to", "2026-10-09", "--dry-run", "--limit", "10"]
        )
        assert args.date_to == date(2026, 10, 9)
        assert args.dry_run is True
        assert args.limit == 10

    def test_janela_vazia_e_erro(self, mod):
        with pytest.raises(SystemExit):
            mod.parse_args(["--date-from", "2026-10-09", "--date-to", "2026-10-09"])


class TestSelecao:
    def test_cobre_flesch_e_content_annotations(self, mod):
        sql = _sql(mod)
        assert "nf.unique_id IS NULL" in sql
        assert (
            "NOT (nf.features ? 'readability_flesch' AND nf.features ? 'content_annotations')"
            in sql
        )

    def test_janela_semiaberta_e_mais_recentes_primeiro(self, mod):
        sql = _sql(mod)
        assert "n.published_at >= %s" in sql
        assert "n.published_at < %s" in sql
        assert "ORDER BY n.published_at DESC" in sql

    def test_select_articles_fecha_conexao(self, mod):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("a1", False, False)]
        with patch.object(mod.psycopg2, "connect", return_value=conn):
            rows = mod.select_articles("postgresql://x", date(2026, 5, 20), date(2026, 10, 6), 5)
        assert rows == [("a1", False, False)]
        cursor.execute.assert_called_once_with(
            mod.SELECT_SQL, (date(2026, 5, 20), date(2026, 10, 6), 5)
        )
        conn.close.assert_called_once()


ROWS = [("a1", False, False), ("a2", True, False), ("a3", False, True)]


@pytest.fixture
def env_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")


class TestMain:
    def test_sem_database_url_retorna_1(self, mod, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert mod.main(["--date-from", "2026-05-20"]) == 1

    def test_dry_run_nao_grava(self, mod, env_db, capsys):
        with (
            patch.object(mod, "select_articles", return_value=ROWS),
            patch.object(mod, "PostgresManager") as pg_cls,
            patch.object(mod, "handle_feature_computation") as handler,
        ):
            assert mod.main(["--date-from", "2026-05-20", "--dry-run"]) == 0
        pg_cls.assert_not_called()
        handler.assert_not_called()
        out = capsys.readouterr().out
        assert "3" in out
        assert "sem readability_flesch: 2" in out
        assert "sem content_annotations: 2" in out
        assert "dry-run" in out

    def test_processa_cada_artigo_com_o_handler_do_worker(self, mod, env_db, capsys):
        computed = {"status": "computed", "features": ["word_count", "readability_flesch"]}
        with (
            patch.object(mod, "select_articles", return_value=ROWS) as select,
            patch.object(mod, "PostgresManager") as pg_cls,
            patch.object(mod, "handle_feature_computation", return_value=computed) as handler,
        ):
            assert mod.main(["--date-from", "2026-05-20", "--date-to", "2026-10-09"]) == 0
        select.assert_called_once_with(
            "postgresql://x", date(2026, 5, 20), date(2026, 10, 9), 50000
        )
        pg = pg_cls.return_value
        assert handler.call_args_list == [call("a1", pg), call("a2", pg), call("a3", pg)]
        pg.close_all.assert_called_once()
        assert "computed=3" in capsys.readouterr().out

    def test_conta_conteudo_curto_sem_flesch(self, mod, env_db, capsys):
        curto = {"status": "computed", "features": ["word_count", "content_annotations"]}
        with (
            patch.object(mod, "select_articles", return_value=ROWS[:1]),
            patch.object(mod, "PostgresManager"),
            patch.object(mod, "handle_feature_computation", return_value=curto),
        ):
            assert mod.main(["--date-from", "2026-05-20"]) == 0
        assert "sem_flesch=1" in capsys.readouterr().out

    def test_falha_em_um_artigo_segue_e_retorna_1(self, mod, env_db, capsys):
        ok = {"status": "computed", "features": ["readability_flesch"]}
        with (
            patch.object(mod, "select_articles", return_value=ROWS),
            patch.object(mod, "PostgresManager") as pg_cls,
            patch.object(
                mod, "handle_feature_computation", side_effect=[ok, RuntimeError("x"), ok]
            ) as handler,
        ):
            assert mod.main(["--date-from", "2026-05-20"]) == 1
        assert handler.call_count == 3
        pg_cls.return_value.close_all.assert_called_once()
        assert "failed=1" in capsys.readouterr().out
