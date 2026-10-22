"""MERGE de dgb_gold.fato_noticias a partir da auditoria news_theme_changes (tema 26).

Fluxo: lê do Postgres o estado ATUAL de tema de todo artigo que aparece na auditoria das
campanhas (tema26 e tema26-rollback), carrega numa tabela de staging no BigQuery
(WRITE_TRUNCATE) e faz MERGE no fato só onde código ou rótulo diverge. Reexecutável: roda na
D0 (depois da 034) e de novo na D1 (depois da reclassificação por LLM).
"""

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


class TestConsultaDoEstado:
    def test_le_o_estado_atual_dos_artigos_da_auditoria(self):
        sql = tc.THEME_CHANGES_STATE_QUERY
        assert "FROM news_theme_changes" in sql
        assert "campaign = ANY(%s)" in sql
        for coluna in THEME_COLUMNS:
            assert f"AS {coluna}" in sql

    def test_mesmos_joins_do_sync_diario(self):
        sql = tc.THEME_CHANGES_STATE_QUERY
        assert "LEFT JOIN themes t1 ON n.theme_l1_id = t1.id" in sql
        assert "LEFT JOIN themes t2 ON n.theme_l2_id = t2.id" in sql
        assert "LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id" in sql

    def test_campanhas_padrao(self):
        assert tc.DEFAULT_CAMPAIGNS == ("tema26", "tema26-rollback")

    @patch("sqlalchemy.create_engine")
    @patch("pandas.read_sql_query")
    def test_fetch_passa_as_campanhas_como_array(self, mock_read_sql, _engine):
        mock_read_sql.return_value = _state()
        df = tc.fetch_theme_changes_state("postgresql://x", ("tema26",))
        assert len(df) == 2
        assert mock_read_sql.call_args.kwargs["params"] == (["tema26"],)


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


def _client(diff_rows: int = 2, merged_rows: int = 2) -> MagicMock:
    client = MagicMock()

    def query(sql, *args, **kwargs):
        job = MagicMock()
        if sql.lstrip().startswith("MERGE"):
            job.num_dml_affected_rows = merged_rows
            job.result.return_value = None
        else:
            job.result.return_value = [(diff_rows,)]
        return job

    client.query.side_effect = query
    return client


class TestMergeThemeChanges:
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
        mock_fetch.return_value = _state(3)
        mock_client_cls.return_value = _client(diff_rows=3, merged_rows=3)

        stats = tc.merge_theme_changes("postgresql://x", "projeto-x")

        assert stats == {
            "campaigns": ["tema26", "tema26-rollback"],
            "staged": 3,
            "fato_rows_to_update": 3,
            "merged": 3,
            "dry_run": False,
        }

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

    def test_campanha_vazia_falha(self):
        with pytest.raises(ValueError, match="campanha"):
            tc.merge_theme_changes("postgresql://x", "projeto-x", campaigns=())
