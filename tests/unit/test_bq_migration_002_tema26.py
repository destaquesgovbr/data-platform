"""BigQuery 002: remap determinístico do tema 26 em dgb_gold.fato_noticias (DP-2, D0).

O fato só tem theme_l1, theme_l2 e most_specific (código + rótulo). A 002 replica, com essas
colunas, a regra da migração 034 do Postgres (o most_specific faz o papel do L3) e pega os
rótulos novos de uma lista inline (dim_temas pode ainda não ter o 26 na D0). O MERGE a partir
da auditoria (`data-platform bq-merge-theme-changes`) reconcilia depois, artigo por artigo,
com o estado do Postgres.
"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_PATH = ROOT / "scripts" / "bigquery" / "migrations" / "002_tema26_remap_fato_noticias.sql"
MIGRATION_034 = ROOT / "scripts" / "migrations" / "034_tema26_defesa_civil.py"


def _sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _migration_034():
    spec = importlib.util.spec_from_file_location("migration_034", MIGRATION_034)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_arquivo_e_a_002():
    assert SQL_PATH.is_file()


def test_atualiza_o_fato_no_projeto_de_producao():
    assert "UPDATE `inspire-7-finep.dgb_gold.fato_noticias`" in _sql()


def test_rotulos_inline_iguais_aos_da_034():
    pares = set(re.findall(r"STRUCT\('([^']+)' AS code, '([^']+)' AS label\)", _sql()))
    assert pares == {(code, label) for code, label, _l, _p in _migration_034().THEMES_26}


def test_renumera_19_03_e_19_04():
    sql = _sql()
    assert r"r'^19\.03', '26.01'" in sql
    assert r"r'^19\.04', '26.02'" in sql


def test_seleciona_so_os_codigos_legados_exatos():
    assert r"r'^19\.0[34](\.0[1-5])?$'" in _sql()


def test_atualiza_codigos_e_rotulos_das_tres_colunas():
    sql = _sql()
    for coluna in ("theme_l1", "theme_l2", "most_specific_theme"):
        assert f"{coluna}_code = s.new_{coluna}_code" in sql
        assert f"{coluna}_label = s.new_{coluna}_label" in sql


def test_casamento_por_unique_id_e_codigos_antigos():
    """Uma linha do fato casa com no máximo uma da origem (o UPDATE ... FROM exige)."""
    sql = _sql()
    assert "f.unique_id = s.unique_id" in sql
    assert "GROUP BY unique_id, l1, l2, ms" in sql


def test_par_l1_l2_coerente_decide_quando_o_most_specific_vai_para_outro_l1():
    """Mesma regra da 034: (19, 19.02, 19.03.01) fica (19, 19.02, 19.02)."""
    sql = _sql()
    assert "AS usa_ms" in sql
    assert "REGEXP_EXTRACT(l2, r'^(.*)\\.')" in sql
