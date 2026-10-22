"""MERGE de dgb_gold.fato_noticias a partir da auditoria news_theme_changes (tema 26).

Contrato de 22/10: o MERGE lê as duas campanhas, tema26-llm-d1 (LLM da D1) e tema26-034 (a
migração), só as linhas não revertidas, do changed_at mais recente para o mais antigo. Leva
ao BigQuery o estado ATUAL de tema (Postgres) desses artigos, numa staging (WRITE_TRUNCATE),
e faz MERGE no fato só onde código ou rótulo diverge; conta os artigos cujo estado atual
diverge da mudança mais recente da auditoria. Reexecutável: D0 (depois da 034) e D1 (depois
da reclassificação por LLM).

Depois do rollback da 034 (que só marca reverted_at), `reverted=True` leva ao fato o estado
atual dos artigos com linhas revertidas e de toda linha do fato que ainda aponta para o 26.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_platform.jobs.bigquery import theme_changes as tc

THEME_COLUMNS = [
    "theme_l1_code",
    "theme_l1_label",
    "theme_l2_code",
    "theme_l2_label",
    "most_specific_theme_code",
    "most_specific_theme_label",
]


def _state(n: int = 2) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unique_id": [f"uid{i}" for i in range(n)],
            "theme_l1_code": ["26"] * n,
            "theme_l1_label": ["Defesa Civil e Gestão de Desastres"] * n,
            "theme_l2_code": ["26.01"] * n,
            "theme_l2_label": ["Defesa Civil"] * n,
            "most_specific_theme_code": ["26.01.03"] * n,
            "most_specific_theme_label": ["Resposta a Desastres"] * n,
        }
    )


MIGRATION_034 = (
    Path(__file__).resolve().parents[4] / "scripts" / "migrations" / "034_tema26_defesa_civil.py"
)


def _migration_034():
    spec = importlib.util.spec_from_file_location("migration_034", MIGRATION_034)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(texto: str) -> str:
    return " ".join(texto.split())


class TestCampanhas:
    def test_as_duas_campanhas_do_contrato(self):
        assert tc.THEME26_CAMPAIGNS == ("tema26-llm-d1", "tema26-034")

    def test_iguais_as_da_migracao_034(self):
        assert tc.THEME26_CAMPAIGNS == _migration_034().THEME26_CAMPAIGNS

    def test_sem_padrao_like(self):
        assert not hasattr(tc, "DEFAULT_CAMPAIGNS")
        for sql in (
            tc.THEME_CHANGES_STATE_QUERY,
            tc.REVERTED_STATE_QUERY,
            tc.campaign_counts_query(reverted=False),
            tc.campaign_counts_query(reverted=True),
        ):
            assert "LIKE" not in sql


class TestConsultaDoEstado:
    def test_le_so_as_linhas_nao_revertidas_das_campanhas(self):
        sql = _sql(tc.THEME_CHANGES_STATE_QUERY)
        assert "FROM news_theme_changes" in sql
        assert "WHERE campaign = ANY(%s) AND reverted_at IS NULL" in sql
        for coluna in THEME_COLUMNS:
            assert f"AS {coluna}" in sql

    def test_mudanca_mais_recente_por_artigo_e_ordem_decrescente(self):
        sql = _sql(tc.THEME_CHANGES_STATE_QUERY)
        assert "SELECT DISTINCT ON (unique_id)" in sql
        assert "ORDER BY unique_id, changed_at DESC, (campaign = %s) DESC, id DESC" in sql
        assert sql.rstrip().endswith("ORDER BY u.changed_at DESC, n.unique_id")

    def test_compara_o_estado_atual_com_a_mudanca_mais_recente(self):
        sql = _sql(tc.THEME_CHANGES_STATE_QUERY)
        assert "t1.code IS DISTINCT FROM u.new_l1_code" in sql
        assert "t2.code IS DISTINCT FROM u.new_l2_code" in sql
        assert "tm.code IS DISTINCT FROM u.new_most_specific_code" in sql
        assert "AS diverges_from_audit" in sql

    def test_mesmos_joins_do_sync_diario(self):
        for query in (tc.THEME_CHANGES_STATE_QUERY, tc.REVERTED_STATE_QUERY, tc.STATE_BY_IDS_QUERY):
            sql = _sql(query)
            assert "LEFT JOIN themes t1 ON n.theme_l1_id = t1.id" in sql
            assert "LEFT JOIN themes t2 ON n.theme_l2_id = t2.id" in sql
            assert "LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id" in sql

    def test_depois_do_rollback_le_as_linhas_revertidas(self):
        sql = _sql(tc.REVERTED_STATE_QUERY)
        assert "WHERE campaign = ANY(%s) AND reverted_at IS NOT NULL" in sql

    def test_estado_por_unique_id(self):
        assert "WHERE n.unique_id = ANY(%s)" in _sql(tc.STATE_BY_IDS_QUERY)

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_fetch_passa_as_campanhas_e_a_do_llm(self, mock_read_sql, _engine):
        mock_read_sql.return_value = _state()
        df = tc.fetch_theme_changes_state("postgresql://x")
        assert len(df) == 2
        assert mock_read_sql.call_args.args[0] == tc.THEME_CHANGES_STATE_QUERY
        assert mock_read_sql.call_args.kwargs["params"] == (
            ["tema26-llm-d1", "tema26-034"],
            "tema26-llm-d1",
        )

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_fetch_depois_do_rollback(self, mock_read_sql, _engine):
        mock_read_sql.return_value = _state()
        tc.fetch_theme_changes_state("postgresql://x", reverted=True)
        assert mock_read_sql.call_args.args[0] == tc.REVERTED_STATE_QUERY
        assert mock_read_sql.call_args.kwargs["params"] == (["tema26-llm-d1", "tema26-034"],)


class TestContagemPorCampanha:
    """O dry-run mostra de que campanhas vieram os artigos (a da D1 não passa calada)."""

    @pytest.mark.parametrize(
        ("reverted", "filtro"),
        [(False, "reverted_at IS NULL"), (True, "reverted_at IS NOT NULL")],
    )
    def test_sql_agrupa_por_campanha_com_o_mesmo_filtro(self, reverted, filtro):
        sql = _sql(tc.campaign_counts_query(reverted=reverted))
        assert "COUNT(DISTINCT unique_id)" in sql
        assert "FROM news_theme_changes" in sql
        assert f"WHERE campaign = ANY(%s) AND {filtro}" in sql
        assert "GROUP BY campaign" in sql

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_devolve_dict_campanha_artigos(self, mock_read_sql, _engine):
        mock_read_sql.return_value = pd.DataFrame(
            {"campaign": ["tema26-034", "tema26-llm-d1"], "articles": [209, 1377]}
        )
        contagem = tc.count_by_campaign("postgresql://x")
        assert contagem == {"tema26-034": 209, "tema26-llm-d1": 1377}
        assert mock_read_sql.call_args.kwargs["params"] == (["tema26-llm-d1", "tema26-034"],)


class TestLinhasDoFatoNo26:
    def test_sql_pega_qualquer_coluna_de_codigo_no_26(self):
        sql = tc.build_fato_26_ids_sql("projeto-x")
        assert "SELECT DISTINCT unique_id" in sql
        assert "FROM `projeto-x.dgb_gold.fato_noticias`" in sql
        for coluna in ("theme_l1_code", "theme_l2_code", "most_specific_theme_code"):
            assert f"REGEXP_CONTAINS(COALESCE({coluna}, ''), r'^26(\\.|$)')" in sql


class TestMergeSql:
    def test_merge_no_fato_a_partir_do_staging(self):
        sql = tc.build_merge_sql("projeto-x")
        assert "MERGE `projeto-x.dgb_gold.fato_noticias` AS f" in sql
        assert "USING `projeto-x.dgb_gold._stg_news_theme_changes` AS s" in sql
        assert "ON f.unique_id = s.unique_id" in sql

    def test_so_atualiza_o_que_diverge(self):
        sql = tc.build_merge_sql("projeto-x")
        assert "WHEN MATCHED AND (" in sql
        for coluna in THEME_COLUMNS:
            assert f"COALESCE(f.{coluna}, '') != COALESCE(s.{coluna}, '')" in sql
            assert f"{coluna} = s.{coluna}" in sql

    def test_contagem_do_dry_run_usa_o_mesmo_criterio(self):
        sql = tc.build_diff_count_sql("projeto-x")
        assert "`projeto-x.dgb_gold.fato_noticias`" in sql
        assert "`projeto-x.dgb_gold._stg_news_theme_changes`" in sql
        for coluna in THEME_COLUMNS:
            assert f"COALESCE(f.{coluna}, '') != COALESCE(s.{coluna}, '')" in sql


def _client(diff_rows: int = 2, merged_rows: int = 2, ids_26: tuple = ()) -> MagicMock:
    client = MagicMock()

    def query(sql, *args, **kwargs):
        job = MagicMock()
        if sql.lstrip().startswith("MERGE"):
            job.num_dml_affected_rows = merged_rows
            job.result.return_value = None
        elif "SELECT DISTINCT unique_id" in sql:
            job.result.return_value = [(uid,) for uid in ids_26]
        else:
            job.result.return_value = [(diff_rows,)]
        return job

    client.query.side_effect = query
    return client


POR_CAMPANHA = {"tema26-034": 209, "tema26-llm-d1": 1377}


class TestMergeThemeChanges:
    @pytest.fixture(autouse=True)
    def contagem(self):
        with patch.object(tc, "count_by_campaign", return_value=POR_CAMPANHA) as mock_count:
            yield mock_count

    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_carrega_staging_com_truncate_e_schema(self, mock_client_cls, mock_fetch):
        mock_fetch.return_value = _state()
        client = _client()
        mock_client_cls.return_value = client

        tc.merge_theme_changes("postgresql://x", "projeto-x")

        (call,) = client.load_table_from_dataframe.call_args_list
        assert call.args[1] == "projeto-x.dgb_gold._stg_news_theme_changes"
        job_config = call.kwargs["job_config"]
        assert job_config.write_disposition == "WRITE_TRUNCATE"
        assert [f.name for f in job_config.schema] == ["unique_id", *THEME_COLUMNS]

    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_aplica_o_merge(self, mock_client_cls, mock_fetch):
        df = _state(3)
        df["diverges_from_audit"] = [False, True, False]
        mock_fetch.return_value = df
        client = _client(diff_rows=3, merged_rows=3)
        mock_client_cls.return_value = client

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x")

        assert stats == {
            "campaigns": ["tema26-llm-d1", "tema26-034"],
            "reverted": False,
            "by_campaign": POR_CAMPANHA,
            "diverges_from_audit": 1,
            "fato_26_unique_ids": None,
            "staged": 3,
            "fato_rows_to_update": 3,
            "merged": 3,
            "dry_run": False,
        }
        mock_fetch.assert_called_once_with("postgresql://x", tc.THEME26_CAMPAIGNS, reverted=False)
        (call,) = client.load_table_from_dataframe.call_args_list
        assert list(call.args[0].columns) == ["unique_id", *THEME_COLUMNS]

    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_dry_run_conta_e_nao_faz_merge(self, mock_client_cls, mock_fetch):
        mock_fetch.return_value = _state(3)
        client = _client(diff_rows=2)
        mock_client_cls.return_value = client

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x", dry_run=True)

        assert stats["fato_rows_to_update"] == 2
        assert stats["merged"] == 0
        assert stats["dry_run"] is True
        sqls = [c.args[0] for c in client.query.call_args_list]
        assert not any(s.lstrip().startswith("MERGE") for s in sqls)

    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_auditoria_vazia_nao_toca_o_bigquery(self, mock_client_cls, mock_fetch):
        mock_fetch.return_value = _state(0)

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x")

        assert stats["staged"] == 0
        assert stats["merged"] == 0
        mock_client_cls.assert_not_called()

    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_contagem_por_campanha_usa_as_mesmas_campanhas(
        self, mock_client_cls, mock_fetch, contagem
    ):
        mock_fetch.return_value = _state(1)
        mock_client_cls.return_value = _client(diff_rows=1, merged_rows=1)

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x", dry_run=True)

        contagem.assert_called_once_with("postgresql://x", tc.THEME26_CAMPAIGNS, reverted=False)
        assert stats["by_campaign"] == POR_CAMPANHA


class TestMergeDepoisDoRollback:
    """reverted=True: linhas revertidas das duas campanhas + linhas do fato ainda no 26."""

    @pytest.fixture(autouse=True)
    def contagem(self):
        with patch.object(tc, "count_by_campaign", return_value=POR_CAMPANHA) as mock_count:
            yield mock_count

    @patch.object(tc, "fetch_state_by_ids")
    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_soma_as_linhas_do_fato_no_26_fora_da_auditoria(
        self, mock_client_cls, mock_fetch, mock_by_ids, contagem
    ):
        mock_fetch.return_value = _state(2)  # uid0, uid1 (revertidos)
        extra = _state(1)
        extra["unique_id"] = ["do_worker"]
        mock_by_ids.return_value = extra
        client = _client(diff_rows=3, merged_rows=3, ids_26=("uid1", "do_worker"))
        mock_client_cls.return_value = client

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x", reverted=True)

        mock_fetch.assert_called_once_with("postgresql://x", tc.THEME26_CAMPAIGNS, reverted=True)
        contagem.assert_called_once_with("postgresql://x", tc.THEME26_CAMPAIGNS, reverted=True)
        mock_by_ids.assert_called_once_with("postgresql://x", ["do_worker"])
        (call,) = client.load_table_from_dataframe.call_args_list
        assert list(call.args[0]["unique_id"]) == ["uid0", "uid1", "do_worker"]
        assert stats["reverted"] is True
        assert stats["fato_26_unique_ids"] == 2
        assert stats["diverges_from_audit"] is None
        assert stats["staged"] == 3
        assert stats["merged"] == 3

    @patch.object(tc, "fetch_state_by_ids")
    @patch.object(tc, "fetch_theme_changes_state")
    @patch("google.cloud.bigquery.Client")
    def test_sem_linhas_no_26_nao_busca_por_id(self, mock_client_cls, mock_fetch, mock_by_ids):
        mock_fetch.return_value = _state(2)
        mock_client_cls.return_value = _client(ids_26=("uid0",))

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x", reverted=True, dry_run=True)

        mock_by_ids.assert_not_called()
        assert stats["staged"] == 2
        assert stats["merged"] == 0

    def test_campanha_vazia_falha(self):
        with pytest.raises(ValueError, match="campanha"):
            tc.merge_theme_changes("postgresql://x", "projeto-x", campaigns=())
