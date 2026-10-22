"""Regras puras da migração 034 (tema 26 Defesa Civil e Gestão de Desastres).

O remap é determinístico por código: 19.03* → 26.01*, 19.04* → 26.02*, com o L1 indo
para 26 quando o ramo do artigo migra. As hierarquias incoerentes que envolvem o 19
(contagens de base de 21/10, seção C.4) têm regra explícita:

  - (15, 19.04, 19.04.04): L2–L3 coerentes, L1 errado → o L3 decide: (26, 26.02, 26.02.04);
  - (19, 19.03, 19.04.01): L3 em outro ramo, mas do mesmo L1 novo → o L3 decide:
    (26, 26.02, 26.02.01);
  - (19, 19.02, 19.03.01): L1–L2 coerentes fora do 26 e o L3 aponta para o 26 → o par
    L1–L2 decide e o L3 sai: (19, 19.02, —); o artigo segue no 19 e vai para a
    reclassificação por LLM da D1;
  - (19, 20.02, 20.02.03): nenhum código em 19.03/19.04 → fora da 034 (D1).

O teste de integração (tests/integration/test_tema26_migration_integration.py) cobre o
SQL contra um Postgres real.
"""

import importlib.util
import itertools
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "scripts" / "migrations" / "034_tema26_defesa_civil.py"
YAML_PATH = ROOT / "test-data" / "themes_tree_enriched_full.yaml"


def _load_module():
    spec = importlib.util.spec_from_file_location("migration_034", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = _load_module()
T = m.ThemeCodes


def _codes(l1, l2, l3, ms=None):
    """Atalho: most_specific = coalesce(l3, l2, l1) quando não informado (é o caso do corpus)."""
    return T(l1, l2, l3, ms if ms is not None else (l3 or l2 or l1))


# --------------------------------------------------------------------------
# Constantes: contrato do tema 26 e o legado que sai
# --------------------------------------------------------------------------

# Rótulos de produção de 19.03*/19.04* (SELECT em themes, 21/10/2026).
LEGADO_PRODUCAO = {
    "19.03": "Defesa Civil",
    "19.03.01": "Preparação para Desastres",
    "19.03.02": "Planejamento de Evacuação",
    "19.03.03": "Resposta a Desastres",
    "19.03.04": "Monitoramento de Riscos Naturais",
    "19.03.05": "Gestão de Abrigos",
    "19.04": "Situações de Emergência",
    "19.04.01": "Resgate e Salvamento",
    "19.04.02": "Logística de Emergência",
    "19.04.03": "Ações Humanitárias",
    "19.04.04": "Reconstrução Pós-Desastre",
    "19.04.05": "Assistência a Deslocados Internos",
}


def _yaml_26() -> set[tuple]:
    def walk(themes, level=1, parent=None):
        for t in themes:
            yield (t["code"], t["label"], level, parent)
            yield from walk(t.get("children") or [], level + 1, t["code"])

    data = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return {row for row in walk(data["themes"]) if row[0].startswith("26")}


class TestConstantes:
    def test_temas_26_iguais_ao_test_data(self):
        assert set(m.THEMES_26) == _yaml_26()

    def test_temas_26_em_ordem_de_insercao_pai_antes_do_filho(self):
        vistos = set()
        for code, _label, _level, parent in m.THEMES_26:
            assert parent is None or parent in vistos, code
            vistos.add(code)

    def test_legado_com_os_rotulos_de_producao(self):
        assert {code: label for code, label, _l, _p in m.LEGACY_THEMES} == LEGADO_PRODUCAO

    def test_legado_com_pais_e_niveis(self):
        for code, _label, level, parent in m.LEGACY_THEMES:
            assert level == code.count(".") + 1
            assert parent == code.rsplit(".", 1)[0]

    def test_mapa_cobre_o_legado_e_preserva_rotulos(self):
        rotulos_26 = {code: label for code, label, _l, _p in m.THEMES_26}
        assert set(m.CODE_MAP) == set(LEGADO_PRODUCAO)
        for old, new in m.CODE_MAP.items():
            assert rotulos_26[new] == LEGADO_PRODUCAO[old], (old, new)

    def test_mapa_renumera_19_03_para_26_01_e_19_04_para_26_02(self):
        assert m.CODE_MAP["19.03"] == "26.01"
        assert m.CODE_MAP["19.03.05"] == "26.01.05"
        assert m.CODE_MAP["19.04"] == "26.02"
        assert m.CODE_MAP["19.04.01"] == "26.02.01"

    def test_mapa_inverso(self):
        assert m.INVERSE_MAP == {new: old for old, new in m.CODE_MAP.items()} | {"26": "19"}

    def test_campanhas_e_origens_do_contrato_de_22_10(self):
        """Contrato da auditoria (plano, 22/10): só duas campanhas, separadas por origem."""
        assert m.CAMPAIGN == "tema26-034"
        assert m.SOURCE == "migration-034"
        assert m.LLM_CAMPAIGN == "tema26-llm-d1"  # DS-1 (data-science#49), source llm:<modelo>

    def test_rollback_percorre_o_llm_e_depois_a_034(self):
        """O rollback (e o MERGE do BigQuery) lê exatamente as duas campanhas do contrato."""
        assert m.THEME26_CAMPAIGNS == ("tema26-llm-d1", "tema26-034")

    def test_sem_campanha_propria_do_rollback(self):
        """O rollback só marca reverted_at: nenhuma terceira campanha na auditoria."""
        for nome in ("ROLLBACK_CAMPAIGN", "ROLLBACK_SOURCE", "CAMPAIGN_PATTERN"):
            assert not hasattr(m, nome), nome


# --------------------------------------------------------------------------
# Tabela de auditoria: contrato com o DS-1 (UNIQUE (campaign, unique_id))
# --------------------------------------------------------------------------


def _sql(texto: str) -> str:
    return " ".join(texto.split())


# Contrato de 22/10: colunas, tipos e nulidade, nesta ordem (mais o UNIQUE).
COLUNAS_DO_CONTRATO = [
    "id BIGSERIAL PRIMARY KEY",
    "campaign VARCHAR(50) NOT NULL",
    "unique_id VARCHAR(120) NOT NULL",
    "old_l1_code VARCHAR(20)",
    "old_l2_code VARCHAR(20)",
    "old_l3_code VARCHAR(20)",
    "old_most_specific_code VARCHAR(20)",
    "new_l1_code VARCHAR(20)",
    "new_l2_code VARCHAR(20)",
    "new_l3_code VARCHAR(20)",
    "new_most_specific_code VARCHAR(20)",
    "source VARCHAR(50) NOT NULL",
    "note TEXT",
    "changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "reverted_at TIMESTAMPTZ",
]


def _create_table_body() -> list[str]:
    sql = m.CREATE_AUDIT_SQL
    inicio = sql.index("CREATE TABLE IF NOT EXISTS news_theme_changes (")
    corpo = sql[inicio : sql.index(");", inicio)].split("(", 1)[1]
    return [_sql(item) for item in re.split(r",\n", corpo) if item.strip()]


class TestContratoDaAuditoria:
    def test_colunas_exatamente_as_do_contrato(self):
        corpo = _create_table_body()
        colunas = [item for item in corpo if not item.startswith("CONSTRAINT")]
        assert colunas == COLUNAS_DO_CONTRATO

    def test_unique_campaign_unique_id_como_constraint_da_tabela(self):
        """UNIQUE (campaign, unique_id) do contrato, sem predicado (preflight do DS-1)."""
        restricoes = [item for item in _create_table_body() if item.startswith("CONSTRAINT")]
        assert restricoes == [
            "CONSTRAINT uq_news_theme_changes_campaign_uid UNIQUE (campaign, unique_id)"
        ]

    def test_sem_indices_fora_do_contrato(self):
        assert "CREATE UNIQUE INDEX" not in m.CREATE_AUDIT_SQL
        assert "CREATE INDEX" not in m.CREATE_AUDIT_SQL

    def test_tabela_pre_existente_sem_unique_e_conferida(self):
        """CREATE TABLE IF NOT EXISTS não cria o UNIQUE numa tabela que já existe."""
        sql = _sql(m.AUDIT_UNIQUE_CHECK_SQL)
        assert "FROM pg_constraint" in sql
        assert "contype = 'u'" in sql
        assert "ARRAY['campaign', 'unique_id']" in sql

    def test_insert_reaplicavel_depois_do_rollback(self):
        """Uma linha por (campanha, artigo): reaplicar sobrescreve e limpa o reverted_at."""
        sql = _sql(m.INSERT_AUDIT_SQL)
        assert "ON CONFLICT (campaign, unique_id) DO UPDATE SET" in sql
        assert "changed_at = EXCLUDED.changed_at" in sql
        assert "reverted_at = NULL" in sql
        for coluna in ("old_l1_code", "new_most_specific_code", "source", "note"):
            assert f"{coluna} = EXCLUDED.{coluna}" in sql, coluna

    def test_rollback_le_as_duas_campanhas_do_mais_recente_para_o_mais_antigo(self):
        sql = _sql(m.AUDIT_ROWS_SQL)
        assert "campaign = ANY(%(campaigns)s)" in sql
        assert "LIKE" not in sql
        assert "reverted_at IS NULL" in sql
        assert "ORDER BY changed_at DESC, (campaign = %(llm_campaign)s) DESC, id DESC" in sql
        assert m.ROLLBACK_SCOPE_PARAMS == {
            "campaigns": ["tema26-llm-d1", "tema26-034"],
            "llm_campaign": "tema26-llm-d1",
        }

    def test_rollback_marca_so_as_linhas_que_leu(self):
        """Linha gravada por um run concorrente depois da leitura não ganha reverted_at."""
        marca = _sql(m.MARK_REVERTED_SQL)
        assert "SET reverted_at = NOW()" in marca
        assert "WHERE id = ANY(%(ids)s)" in marca
        assert "RETURNING campaign" in marca


# --------------------------------------------------------------------------
# chain / map_code
# --------------------------------------------------------------------------


class TestHierarquiaPorCodigo:
    @pytest.mark.parametrize(
        ("code", "esperado"),
        [
            ("26.01.03", T("26", "26.01", "26.01.03", "26.01.03")),
            ("26.02", T("26", "26.02", None, "26.02")),
            ("19", T("19", None, None, "19")),
        ],
    )
    def test_chain(self, code, esperado):
        assert m.chain(code) == esperado

    def test_map_code(self):
        assert m.map_code("19.03.03") == "26.01.03"
        assert m.map_code("19.05.01") == "19.05.01"
        assert m.map_code("19") == "19"
        assert m.map_code(None) is None


# --------------------------------------------------------------------------
# remap: os padrões reais do corpus (9 combinações, 209 artigos em 21/10)
# --------------------------------------------------------------------------


class TestRemap:
    @pytest.mark.parametrize(
        ("antigo", "novo"),
        [
            (_codes("19", "19.03", "19.03.03"), _codes("26", "26.01", "26.01.03")),
            (_codes("19", "19.03", "19.03.01"), _codes("26", "26.01", "26.01.01")),
            (_codes("19", "19.03", "19.03.04"), _codes("26", "26.01", "26.01.04")),
            (_codes("19", "19.04", "19.04.03"), _codes("26", "26.02", "26.02.03")),
            (_codes("19", "19.04", "19.04.01"), _codes("26", "26.02", "26.02.01")),
            (_codes("19", "19.04", "19.04.02"), _codes("26", "26.02", "26.02.02")),
        ],
    )
    def test_hierarquia_coerente_remapeia_por_codigo(self, antigo, novo):
        assert m.remap(antigo) == (novo, "remap")

    def test_so_l2_remapeia(self):
        assert m.remap(_codes("19", "19.03", None)) == (_codes("26", "26.01", None), "remap")

    def test_l1_errado_com_l2_l3_coerentes_o_l3_decide(self):
        """(15, 19.04, 19.04.04): Rio Bonito do Iguaçu (MDR), reconstrução pós-desastre."""
        assert m.remap(_codes("15", "19.04", "19.04.04")) == (
            _codes("26", "26.02", "26.02.04"),
            "hierarquia_reconstruida",
        )

    def test_l3_de_outro_ramo_do_mesmo_l1_novo_o_l3_decide(self):
        """(19, 19.03, 19.04.01): queda de avião em BH (Agência Brasil), resgate."""
        assert m.remap(_codes("19", "19.03", "19.04.01")) == (
            _codes("26", "26.02", "26.02.01"),
            "hierarquia_reconstruida",
        )

    def test_par_l1_l2_coerente_fora_do_26_descarta_o_l3(self):
        """(19, 19.02, 19.03.01): visita técnica da ESD ao Chile; é tema militar, fica no 19."""
        assert m.remap(_codes("19", "19.02", "19.03.01")) == (
            _codes("19", "19.02", None),
            "l3_descartado",
        )

    def test_sem_codigo_legado_fica_como_esta(self):
        """(19, 20.02, 20.02.03): incoerente, mas fora da 034 (vai para a D1)."""
        antigo = _codes("19", "20.02", "20.02.03")
        assert m.remap(antigo) == (antigo, "sem_codigo_legado")

    def test_l2_legado_com_l3_de_fora_e_par_coerente_o_par_decide(self):
        assert m.remap(_codes("19", "19.03", "05.02.01")) == (
            _codes("26", "26.01", None),
            "l3_descartado",
        )

    def test_l2_legado_com_l3_de_fora_e_par_incoerente_o_l3_decide(self):
        assert m.remap(_codes("15", "19.03", "05.02.01")) == (
            _codes("05", "05.02", "05.02.01"),
            "hierarquia_reconstruida",
        )

    def test_most_specific_divergente_e_reconstruido(self):
        assert m.remap(T("19", "19.01", "19.01.02", "19.03.03")) == (
            _codes("19", "19.01", "19.01.02"),
            "hierarquia_reconstruida",
        )

    def test_so_most_specific(self):
        assert m.remap(T(None, None, None, "19.03")) == (
            _codes("26", "26.01", None),
            "hierarquia_reconstruida",
        )

    def test_l3_sem_l2(self):
        assert m.remap(_codes("19", None, "19.03.03")) == (
            _codes("26", "26.01", "26.01.03"),
            "hierarquia_reconstruida",
        )


AMOSTRA = [
    None,
    "19",
    "15",
    "05",
    "19.02",
    "19.03",
    "19.04",
    "05.02",
    "19.02.01",
    "19.03.01",
    "19.04.04",
    "05.02.01",
]


def _combinacoes():
    for l1, l2, l3, ms in itertools.product(AMOSTRA, repeat=4):
        codes = T(l1, l2, l3, ms)
        if m.touches_legacy(codes):
            yield codes


class TestPropriedadesDoRemap:
    def test_resultado_sem_codigo_legado_e_hierarquia_coerente(self):
        for antigo in _combinacoes():
            novo, _regra = m.remap(antigo)
            assert not m.touches_legacy(novo), antigo
            assert novo.most_specific is not None, antigo
            assert novo == m.chain(novo.most_specific), antigo

    def test_idempotente(self):
        for antigo in _combinacoes():
            novo, _ = m.remap(antigo)
            assert m.remap(novo) == (novo, "sem_codigo_legado")

    def test_l1_vai_para_26_quando_o_mais_especifico_novo_e_do_26(self):
        for antigo in _combinacoes():
            novo, _ = m.remap(antigo)
            if novo.most_specific.startswith("26"):
                assert novo.l1 == "26"


# --------------------------------------------------------------------------
# Rollback: alvo a partir da auditoria e mapa inverso
# --------------------------------------------------------------------------


class TestPontasDaAuditoria:
    """Estado antes da PRIMEIRA mudança e depois da ÚLTIMA, por artigo, percorrendo as
    duas campanhas (LLM da D1 e 034) do changed_at mais recente para o mais antigo."""

    t0 = "2026-11-10T22:00:00+00:00"
    t1 = "2026-11-11T10:00:00+00:00"
    original = _codes("19", "19.03", "19.03.03")
    pos_034 = _codes("26", "26.01", "26.01.03")
    pos_llm = _codes("26", "26.02", "26.02.01")

    def test_uma_campanha(self):
        rows = [("a", "tema26-034", self.t0, 1, self.original, self.pos_034)]
        first_old, last_new = m.audit_endpoints(rows)
        assert first_old == {"a": self.original}
        assert last_new == {"a": self.pos_034}

    def test_034_e_depois_o_llm(self):
        rows = [
            ("a", "tema26-034", self.t0, 1, self.original, self.pos_034),
            ("a", "tema26-llm-d1", self.t1, 900, self.pos_034, self.pos_llm),
        ]
        first_old, last_new = m.audit_endpoints(rows)
        assert first_old == {"a": self.original}
        assert last_new == {"a": self.pos_llm}

    def test_ordem_e_por_changed_at_e_nao_pela_lista(self):
        rows = [
            ("a", "tema26-llm-d1", self.t1, 900, self.pos_034, self.pos_llm),
            ("a", "tema26-034", self.t0, 1, self.original, self.pos_034),
        ]
        first_old, last_new = m.audit_endpoints(rows)
        assert first_old == {"a": self.original}
        assert last_new == {"a": self.pos_llm}

    def test_empate_no_changed_at_desfaz_o_llm_antes_da_034(self):
        """Mesmo changed_at: a do LLM é a mais recente, qualquer que seja o id."""
        rows = [
            ("a", "tema26-034", self.t0, 9, self.original, self.pos_034),
            ("a", "tema26-llm-d1", self.t0, 2, self.pos_034, self.pos_llm),
        ]
        first_old, last_new = m.audit_endpoints(rows)
        assert first_old == {"a": self.original}
        assert last_new == {"a": self.pos_llm}

    def test_percorre_do_mais_recente_para_o_mais_antigo(self):
        """A ordem de percurso é a do contrato: changed_at decrescente."""
        rows = [
            ("a", "tema26-034", self.t0, 1, self.original, self.pos_034),
            ("a", "tema26-llm-d1", self.t1, 900, self.pos_034, self.pos_llm),
            ("b", "tema26-034", self.t1, 2, self.original, self.pos_034),
        ]
        assert [(r[0], r[1]) for r in m.rollback_order(rows)] == [
            ("a", "tema26-llm-d1"),  # empate em t1 com b: o LLM primeiro
            ("b", "tema26-034"),
            ("a", "tema26-034"),
        ]

    def test_artigo_de_fora_do_19_movido_so_pelo_llm(self):
        """05.02.01 → 26.02.01 na D1: o rollback tem de voltar a 05.02.01, não ao 19."""
        clima = _codes("05", "05.02", "05.02.01")
        rows = [("c", "tema26-llm-d1", self.t1, 5, clima, self.pos_llm)]
        first_old, last_new = m.audit_endpoints(rows)
        assert first_old == {"c": clima}
        assert last_new == {"c": self.pos_llm}
        assert m.rollback_target(self.pos_llm, first_old["c"], last_new["c"]) == (
            clima,
            "revertido",
        )


class TestRollback:
    antes = _codes("19", "19.03", "19.03.03")
    depois = _codes("26", "26.01", "26.01.03")

    def test_estado_igual_ao_da_auditoria_volta_ao_original(self):
        assert m.rollback_target(self.depois, self.antes, self.depois) == (self.antes, "revertido")

    def test_estado_mudado_mas_ainda_no_26_volta_a_forca(self):
        atual = _codes("26", "26.02", "26.02.01")
        assert m.rollback_target(atual, self.antes, self.depois) == (
            self.antes,
            "revertido_forcado",
        )

    def test_estado_mudado_fora_do_26_fica(self):
        atual = _codes("05", "05.02", "05.02.01")
        assert m.rollback_target(atual, self.antes, self.depois) == (None, "mantido")

    def test_mapa_inverso_por_coluna(self):
        assert m.inverse(_codes("26", "26.01", "26.01.03")) == _codes("19", "19.03", "19.03.03")
        assert m.inverse(_codes("26", "26.02", None)) == _codes("19", "19.04", None)
        fora = _codes("04", "04.03", "04.03.01")
        assert m.inverse(fora) == fora

    def test_references_26(self):
        assert m.references_26(_codes("26", "26.01", None))
        assert m.references_26(T("19", "19.02", "19.02.01", "26.01"))
        assert not m.references_26(_codes("19", "19.02", "19.02.01"))


# --------------------------------------------------------------------------
# Contagens por código (dry-run)
# --------------------------------------------------------------------------


class TestContagens:
    def test_transicoes_por_coluna(self):
        pares = [
            (_codes("19", "19.03", "19.03.03"), _codes("26", "26.01", "26.01.03")),
            (_codes("19", "19.03", "19.03.03"), _codes("26", "26.01", "26.01.03")),
            (_codes("19", "19.02", "19.03.01"), _codes("19", "19.02", None)),
        ]
        contagens = m.transition_counts(pares)
        assert contagens["theme_l1"] == {"19→26": 2}
        assert contagens["theme_l2"] == {"19.03→26.01": 2}
        assert contagens["theme_l3"] == {"19.03.03→26.01.03": 2, "19.03.01→∅": 1}
        assert contagens["most_specific"] == {"19.03.03→26.01.03": 2, "19.03.01→19.02": 1}
