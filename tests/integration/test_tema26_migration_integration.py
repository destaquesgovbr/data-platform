"""
Integração da migração 034 (tema 26) contra PostgreSQL real, pelo runner.

Banco descartável de test_migrate_integration.py (MIGRATION_TEST_DATABASE_URL): baseline
+ `stamp 033`, para que `migrate` rode só a 034. O corpus semeado reproduz os padrões de
produção de 21/10 (contagens de base, seção C): hierarquias coerentes em 19.03/19.04,
só-L2, as 4 incoerentes que envolvem o 19 e artigos fora do escopo.

Contrato da auditoria (plano, 22/10) com o DS-1 (data-science#49): as colunas do contrato,
UNIQUE (campaign, unique_id), campanha `tema26-034` (source `migration-034`) para a 034 e
`tema26-llm-d1` (source `llm:<modelo>`) para a reclassificação por LLM da D1. O rollback lê
só essas duas, do changed_at mais recente para o mais antigo, e só marca reverted_at. O
preflight do DS-1 está copiado abaixo (DS1_*) e roda contra a tabela que a 034 cria.
"""

import importlib.util
from pathlib import Path

import psycopg2
import pytest

from tests.integration.test_migrate_integration import (
    DATABASE_URL,
    _execute,
    _reset_database,
    _run_migrate,
)


def _execute_params(sql: str, params: tuple) -> list[tuple]:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


MIGRATION = Path(__file__).parents[2] / "scripts" / "migrations" / "034_tema26_defesa_civil.py"

THEMES = [
    ("04", "Segurança Pública", 1, None),
    ("05", "Meio Ambiente e Sustentabilidade", 1, None),
    ("15", "Desenvolvimento Social", 1, None),
    ("19", "Defesa e Forças Armadas", 1, None),
    ("20", "Políticas Públicas e Governança", 1, None),
    ("04.03", "Prevenção e Combate ao Crime", 2, "04"),
    ("05.02", "Mudanças Climáticas", 2, "05"),
    ("15.02", "Combate à Pobreza", 2, "15"),
    ("19.01", "Segurança Nacional", 2, "19"),
    ("19.02", "Missões Militares", 2, "19"),
    ("19.03", "Defesa Civil", 2, "19"),
    ("19.04", "Situações de Emergência", 2, "19"),
    ("19.05", "Políticas e Estratégias de Defesa", 2, "19"),
    ("20.02", "Gestão Pública", 2, "20"),
    ("04.03.01", "Prevenção à Violência", 3, "04.03"),
    ("05.02.01", "Catástrofes Climáticas", 3, "05.02"),
    ("15.02.03", "Apoio Emergencial", 3, "15.02"),
    ("19.01.02", "Proteção de Infraestruturas Críticas", 3, "19.01"),
    ("19.02.01", "Operações de Paz", 3, "19.02"),
    ("19.03.01", "Preparação para Desastres", 3, "19.03"),
    ("19.03.02", "Planejamento de Evacuação", 3, "19.03"),
    ("19.03.03", "Resposta a Desastres", 3, "19.03"),
    ("19.03.04", "Monitoramento de Riscos Naturais", 3, "19.03"),
    ("19.03.05", "Gestão de Abrigos", 3, "19.03"),
    ("19.04.01", "Resgate e Salvamento", 3, "19.04"),
    ("19.04.02", "Logística de Emergência", 3, "19.04"),
    ("19.04.03", "Ações Humanitárias", 3, "19.04"),
    ("19.04.04", "Reconstrução Pós-Desastre", 3, "19.04"),
    ("19.04.05", "Assistência a Deslocados Internos", 3, "19.04"),
    ("19.05.01", "Planejamento de Defesa Nacional", 3, "19.05"),
    ("20.02.03", "Transparência", 3, "20.02"),
]

# unique_id → (l1, l2, l3, most_specific) antes da 034
CORPUS = {
    "dc1": ("19", "19.03", "19.03.03", "19.03.03"),
    "dc2": ("19", "19.03", "19.03.03", "19.03.03"),
    "dc3": ("19", "19.03", "19.03.01", "19.03.01"),
    "em1": ("19", "19.04", "19.04.03", "19.04.03"),
    "so_l2": ("19", "19.03", None, "19.03"),
    "inc_15": ("15", "19.04", "19.04.04", "19.04.04"),
    "inc_esd": ("19", "19.02", "19.03.01", "19.03.01"),
    "inc_bh": ("19", "19.03", "19.04.01", "19.04.01"),
    "inc_20": ("19", "20.02", "20.02.03", "20.02.03"),
    "militar": ("19", "19.01", "19.01.02", "19.01.02"),
    "clima": ("05", "05.02", "05.02.01", "05.02.01"),
    "sem_tema": (None, None, None, None),
}

ESPERADO_APOS_034 = {
    "dc1": ("26", "26.01", "26.01.03", "26.01.03"),
    "dc2": ("26", "26.01", "26.01.03", "26.01.03"),
    "dc3": ("26", "26.01", "26.01.01", "26.01.01"),
    "em1": ("26", "26.02", "26.02.03", "26.02.03"),
    "so_l2": ("26", "26.01", None, "26.01"),
    "inc_15": ("26", "26.02", "26.02.04", "26.02.04"),
    "inc_esd": ("19", "19.02", None, "19.02"),
    "inc_bh": ("26", "26.02", "26.02.01", "26.02.01"),
    "inc_20": ("19", "20.02", "20.02.03", "20.02.03"),
    "militar": ("19", "19.01", "19.01.02", "19.01.02"),
    "clima": ("05", "05.02", "05.02.01", "05.02.01"),
    "sem_tema": (None, None, None, None),
}

TOCADOS = {"dc1", "dc2", "dc3", "em1", "so_l2", "inc_15", "inc_esd", "inc_bh"}

LLM_CAMPAIGN = "tema26-llm-d1"
LLM_SOURCE = "llm:us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Cópia do preflight do DS-1 (data-science#49, scripts/reenrich_combined_window.py:
# AUDIT_REQUIRED_COLUMNS, AUDIT_UNIQUE_SQL e CAMPAIGN_FOREIGN_SOURCES_SQL). Sem isso o
# script sai com 1, inclusive no --dry-run, e a D1 inteira fica bloqueada.
DS1_AUDIT_REQUIRED_COLUMNS = (
    "campaign",
    "unique_id",
    "old_l1_code",
    "old_l2_code",
    "old_l3_code",
    "old_most_specific_code",
    "new_l1_code",
    "new_l2_code",
    "new_l3_code",
    "new_most_specific_code",
    "source",
    "changed_at",
)
DS1_AUDIT_COLUMNS_SQL = """
    SELECT column_name FROM information_schema.columns
    WHERE table_name = %s AND table_schema = current_schema()
"""
DS1_AUDIT_UNIQUE_SQL = """
    SELECT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid = to_regclass(%s)
          AND i.indisunique
          AND i.indpred IS NULL
          AND i.indnkeyatts = 2
          AND (
              SELECT array_agg(a.attname::text ORDER BY a.attname::text)
              FROM pg_attribute a
              WHERE a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey::int2[])
          ) = ARRAY['campaign', 'unique_id']
    )
"""
DS1_CAMPAIGN_FOREIGN_SOURCES_SQL = """
    SELECT DISTINCT source FROM news_theme_changes
    WHERE campaign = %s AND source NOT LIKE %s
    ORDER BY source
    LIMIT 5
"""

LEGADO = [
    "19.03",
    "19.03.01",
    "19.03.02",
    "19.03.03",
    "19.03.04",
    "19.03.05",
    "19.04",
    "19.04.01",
    "19.04.02",
    "19.04.03",
    "19.04.04",
    "19.04.05",
]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("migration_034", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_themes(themes) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for code, label, level, parent in themes:
                cur.execute(
                    "INSERT INTO themes (code, label, full_name, level, parent_code) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (code, label, f"{code} {label}", level, parent),
                )
        conn.commit()
    finally:
        conn.close()


def _set_news(unique_id: str, codes: tuple, insert: bool = False) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            ids = []
            for code in codes:
                if code is None:
                    ids.append(None)
                else:
                    cur.execute("SELECT id FROM themes WHERE code = %s", (code,))
                    ids.append(cur.fetchone()[0])
            if insert:
                cur.execute(
                    "INSERT INTO news (unique_id, agency_id, title, published_at, agency_key, "
                    "theme_l1_id, theme_l2_id, theme_l3_id, most_specific_theme_id) "
                    "SELECT %s, id, 'Título', '2026-10-01T12:00:00+00:00', key, %s, %s, %s, %s "
                    "FROM agencies WHERE key = 'mdr'",
                    (unique_id, *ids),
                )
            else:
                cur.execute(
                    "UPDATE news SET theme_l1_id = %s, theme_l2_id = %s, theme_l3_id = %s, "
                    "most_specific_theme_id = %s WHERE unique_id = %s",
                    (*ids, unique_id),
                )
        conn.commit()
    finally:
        conn.close()


def _news_codes() -> dict[str, tuple]:
    rows = _execute(
        "SELECT n.unique_id, t1.code, t2.code, t3.code, tm.code FROM news n "
        "LEFT JOIN themes t1 ON t1.id = n.theme_l1_id "
        "LEFT JOIN themes t2 ON t2.id = n.theme_l2_id "
        "LEFT JOIN themes t3 ON t3.id = n.theme_l3_id "
        "LEFT JOIN themes tm ON tm.id = n.most_specific_theme_id"
    )
    return {uid: (l1, l2, l3, ms) for uid, l1, l2, l3, ms in rows}


def _theme_codes() -> set[str]:
    return {code for (code,) in _execute("SELECT code FROM themes")}


def _audit_table_exists() -> bool:
    return _execute("SELECT to_regclass('news_theme_changes') IS NOT NULL") == [(True,)]


def _audit(campaign: str = "tema26-034") -> list[tuple]:
    return _execute(
        "SELECT unique_id, old_l1_code, old_l2_code, old_l3_code, old_most_specific_code, "
        "new_l1_code, new_l2_code, new_l3_code, new_most_specific_code, source, note, "
        "reverted_at IS NOT NULL "
        f"FROM news_theme_changes WHERE campaign = '{campaign}' ORDER BY id"
    )


def _campanhas() -> set[str]:
    return {
        campaign for (campaign,) in _execute("SELECT DISTINCT campaign FROM news_theme_changes")
    }


def _log_audit(
    unique_id: str,
    old: tuple,
    new: tuple,
    campaign: str = LLM_CAMPAIGN,
    source: str = LLM_SOURCE,
) -> None:
    """Grava como o DS-1 (INSERT_AUDIT_SQL do data-science#49: sem note, sem ON CONFLICT)."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news_theme_changes (campaign, unique_id, old_l1_code, old_l2_code, "
                "old_l3_code, old_most_specific_code, new_l1_code, new_l2_code, new_l3_code, "
                "new_most_specific_code, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (campaign, unique_id, *old, *new, source),
            )
        conn.commit()
    finally:
        conn.close()


def _d1_llm() -> None:
    """D1 simulada depois da 034: o LLM move 3 artigos, cada um na campanha do DS-1.

    - inc_esd: ficou no 19 pela 034 (l3_descartado) e o LLM o põe no 26;
    - clima: de 05.02.01 (bloco extra, sem auditoria da 034) para o 26;
    - militar: dentro do 19 (19.01.02 → 19.05.01).
    """
    for uid, old, new in (
        ("inc_esd", ESPERADO_APOS_034["inc_esd"], ("26", "26.01", "26.01.03", "26.01.03")),
        ("clima", CORPUS["clima"], ("26", "26.02", "26.02.01", "26.02.01")),
        ("militar", CORPUS["militar"], ("19", "19.05", "19.05.01", "19.05.01")),
    ):
        _set_news(uid, new)
        _log_audit(uid, old, new)


def _run_module(mod, action: str, dry_run: bool) -> dict:
    """Chama migrate/rollback do módulo numa conexão própria, com o commit do runner."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        result = getattr(mod, action)(conn, dry_run=dry_run)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return result
    finally:
        conn.close()


def _seed_corpus() -> None:
    _execute("INSERT INTO agencies (key, name) VALUES ('mdr', 'MDR')")
    _seed_themes(THEMES)
    for unique_id, codes in CORPUS.items():
        _set_news(unique_id, codes, insert=True)


@pytest.fixture(autouse=True)
def seeded_database():
    _reset_database()
    result = _run_migrate("stamp", "033", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    _seed_corpus()
    yield


@pytest.mark.integration
class TestDryRun:
    def test_runner_dry_run_nao_muda_nada(self):
        result = _run_migrate("migrate", "--dry-run")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "034_tema26_defesa_civil" in result.stdout
        assert _news_codes() == CORPUS
        assert not _audit_table_exists()
        assert "26" not in _theme_codes()

    def test_dry_run_conta_por_codigo_e_por_regra(self, mod):
        stats = _run_module(mod, "migrate", dry_run=True)

        assert stats["dry_run"] is True
        assert stats["articles"] == len(TOCADOS)
        assert stats["by_rule"] == {"remap": 5, "hierarquia_reconstruida": 2, "l3_descartado": 1}
        assert stats["transitions"]["theme_l1"] == {"19→26": 6, "15→26": 1}
        assert stats["transitions"]["theme_l2"] == {
            "19.03→26.01": 4,
            "19.04→26.02": 2,
            "19.03→26.02": 1,
        }
        assert stats["transitions"]["theme_l3"] == {
            "19.03.03→26.01.03": 2,
            "19.03.01→26.01.01": 1,
            "19.04.03→26.02.03": 1,
            "19.04.04→26.02.04": 1,
            "19.03.01→∅": 1,
            "19.04.01→26.02.01": 1,
        }
        assert stats["legacy_refs_before"] == {
            "19.03": 5,
            "19.03.01": 2,
            "19.03.03": 2,
            "19.04": 2,
            "19.04.01": 1,
            "19.04.03": 1,
            "19.04.04": 1,
        }
        assert stats["themes_inserted"] == 13
        assert stats["legacy_themes_deleted"] == 12
        assert stats["inconsistent_l1_19_26_after"] == 1  # inc_20, fica para a D1
        assert _news_codes() == CORPUS
        assert "26" not in _theme_codes()


@pytest.mark.integration
class TestApply:
    def test_runner_aplica_remap_e_troca_os_temas(self):
        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, result.stdout + result.stderr

        assert _news_codes() == ESPERADO_APOS_034
        temas = _theme_codes()
        assert not temas & set(LEGADO)
        assert {"19", "19.01", "19.02", "19.05", "26", "26.01", "26.02.05"} <= temas

    def test_temas_26_com_rotulos_pais_e_full_name(self, mod):
        _run_migrate("migrate", "--yes")
        rows = _execute(
            "SELECT code, label, level, parent_code, full_name FROM themes "
            "WHERE code LIKE '26%' ORDER BY code COLLATE \"C\""
        )
        assert [r[:4] for r in rows] == sorted(mod.THEMES_26, key=lambda t: t[0])
        assert all(full == f"{code} {label}" for code, label, _l, _p, full in rows)

    def test_auditoria_uma_linha_por_artigo_tocado(self):
        _run_migrate("migrate", "--yes")
        audit = _audit()
        assert {row[0] for row in audit} == TOCADOS
        assert len(audit) == len(TOCADOS)
        for uid, *codes, source, note, reverted in audit:
            assert tuple(codes[:4]) == CORPUS[uid]
            assert tuple(codes[4:]) == ESPERADO_APOS_034[uid]
            assert source == "migration-034"
            assert note in {"remap", "hierarquia_reconstruida", "l3_descartado"}
            assert reverted is False

    def test_artigos_fora_do_escopo_nao_sao_tocados(self):
        antes = dict(_execute("SELECT unique_id, updated_at FROM news"))
        _run_migrate("migrate", "--yes")
        depois = dict(_execute("SELECT unique_id, updated_at FROM news"))
        for uid in set(CORPUS) - TOCADOS:
            assert depois[uid] == antes[uid], uid

    def test_reaplicar_e_no_op(self, mod):
        _run_migrate("migrate", "--yes")
        stats = _run_module(mod, "migrate", dry_run=False)
        assert stats["articles"] == 0
        assert stats["themes_inserted"] == 0
        assert _news_codes() == ESPERADO_APOS_034
        assert len(_audit()) == len(TOCADOS)

    def test_codigo_legado_fora_do_contrato_aborta(self, mod):
        _seed_themes([("19.03.06", "Inesperado", 3, "19.03")])
        with pytest.raises(ValueError, match="19.03.06"):
            _run_module(mod, "migrate", dry_run=False)
        assert _news_codes() == CORPUS

    def test_banco_vazio_so_cria_o_26(self, mod):
        _reset_database()
        stats = _run_module(mod, "migrate", dry_run=False)
        assert stats["articles"] == 0
        assert _theme_codes() == {code for code, *_ in mod.THEMES_26}
        stats = _run_module(mod, "rollback", dry_run=False)
        assert _theme_codes() == set()


@pytest.mark.integration
class TestRollback:
    def test_runner_rollback_volta_ao_estado_original(self):
        _run_migrate("migrate", "--yes")
        result = _run_migrate("rollback", "034", "--yes")
        assert result.returncode == 0, result.stdout + result.stderr

        assert _news_codes() == CORPUS
        temas = _theme_codes()
        assert set(LEGADO) <= temas
        assert not {code for code in temas if code.startswith("26")}
        legado = _execute(
            "SELECT code, label, parent_code FROM themes "
            "WHERE code LIKE '19.03%' OR code LIKE '19.04%'"
        )
        assert {(c, lbl, p) for c, lbl, _lv, p in THEMES if c in LEGADO} == set(legado)

    def test_rollback_so_marca_reverted_at_sem_campanha_nova(self):
        """O contrato tem duas campanhas: o rollback marca as linhas que desfez e só."""
        _run_migrate("migrate", "--yes")
        _run_migrate("rollback", "034", "--yes")
        audit = _audit()
        assert {row[0] for row in audit} == TOCADOS
        assert all(row[-1] for row in audit)
        assert _campanhas() == {"tema26-034"}

    def test_rollback_desfaz_tambem_a_reclassificacao_por_llm(self, mod):
        _run_migrate("migrate", "--yes")
        _d1_llm()

        stats = _run_module(mod, "rollback", dry_run=False)

        assert _news_codes() == CORPUS
        assert stats["by_reason"] == {"revertido": len(TOCADOS) + 2}
        assert stats["campaign_rows_reverted"] == {"tema26-034": len(TOCADOS), LLM_CAMPAIGN: 3}
        assert all(row[-1] for row in _audit(LLM_CAMPAIGN))
        assert _campanhas() == {"tema26-034", LLM_CAMPAIGN}

    def test_campanha_fora_do_contrato_nao_e_lida(self, mod):
        """Só tema26-llm-d1 e tema26-034: outra campanha, mesmo tema26-*, fica intacta."""
        _run_migrate("migrate", "--yes")
        novo = ("19", "19.05", "19.05.01", "19.05.01")
        _set_news("militar", novo)
        _log_audit("militar", CORPUS["militar"], novo, campaign="tema26-llm-d1b")

        stats = _run_module(mod, "rollback", dry_run=False)

        assert _news_codes()["militar"] == novo
        assert _audit("tema26-llm-d1b")[0][-1] is False
        assert stats["campaign_rows_reverted"] == {"tema26-034": len(TOCADOS)}

    def test_linha_gravada_depois_da_leitura_nao_e_marcada(self, mod):
        """Só as linhas lidas pelo rollback ganham reverted_at (marca por id).

        Fora do teste, o CREATE ... IF NOT EXISTS do rollback já segura um insert
        concorrente até o commit; aqui a linha entra na mesma transação, depois da leitura.
        """
        _run_migrate("migrate", "--yes")
        conn = psycopg2.connect(DATABASE_URL)
        try:
            cursor = conn.cursor()
            original = mod.audit_endpoints

            def le_e_grava_concorrente(rows):
                cursor.execute(
                    "INSERT INTO news_theme_changes (campaign, unique_id, old_l1_code, "
                    "new_l1_code, source) VALUES (%s, 'militar', '19', '19', %s)",
                    (LLM_CAMPAIGN, LLM_SOURCE),
                )
                return original(rows)

            mod.audit_endpoints = le_e_grava_concorrente
            try:
                stats = mod._revert(cursor)
            finally:
                mod.audit_endpoints = original
            conn.commit()
        finally:
            conn.close()
        assert stats["campaign_rows_reverted"] == {"tema26-034": len(TOCADOS)}
        assert _audit(LLM_CAMPAIGN)[0][-1] is False

    def test_artigo_movido_para_o_26_so_pelo_llm_volta_ao_tema_original(self, mod):
        """05.02.01 → 26.02.01 na campanha do LLM volta a 05.02.01, não a 19.04.01."""
        _run_migrate("migrate", "--yes")
        _d1_llm()

        _run_module(mod, "rollback", dry_run=False)

        assert _news_codes()["clima"] == ("05", "05.02", "05.02.01", "05.02.01")
        assert _news_codes()["militar"] == CORPUS["militar"]

    def test_artigo_no_26_fora_da_auditoria_volta_pelo_mapa_inverso(self, mod):
        _run_migrate("migrate", "--yes")
        _set_news("novo_do_worker", ("26", "26.01", "26.01.03", "26.01.03"), insert=True)

        stats = _run_module(mod, "rollback", dry_run=False)

        assert _news_codes()["novo_do_worker"] == ("19", "19.03", "19.03.03", "19.03.03")
        assert stats["by_reason"]["mapa_inverso"] == 1
        # Fora da auditoria (contrato sem campanha de rollback): fica no log do rollback.
        assert stats["unaudited_inverse_map"] == ["novo_do_worker"]
        assert "novo_do_worker" not in {row[0] for row in _audit()}
        assert _campanhas() == {"tema26-034"}

    def test_artigo_alterado_depois_e_fora_do_26_fica(self, mod):
        _run_migrate("migrate", "--yes")
        _set_news("dc1", ("05", "05.02", "05.02.01", "05.02.01"))

        stats = _run_module(mod, "rollback", dry_run=False)

        assert _news_codes()["dc1"] == ("05", "05.02", "05.02.01", "05.02.01")
        assert stats["by_reason"]["mantido"] == 1

    def test_dry_run_do_rollback_nao_muda_nada(self, mod):
        _run_migrate("migrate", "--yes")
        stats = _run_module(mod, "rollback", dry_run=True)
        assert stats["dry_run"] is True
        assert stats["by_reason"] == {"revertido": len(TOCADOS)}
        assert _news_codes() == ESPERADO_APOS_034
        assert not any(row[-1] for row in _audit())

    def test_reaplicar_depois_do_rollback(self):
        _run_migrate("migrate", "--yes")
        _run_migrate("rollback", "034", "--yes")
        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _news_codes() == ESPERADO_APOS_034
        audit = _audit()
        assert len(audit) == len(TOCADOS)  # UNIQUE: a linha é reaproveitada
        assert {row[0] for row in audit} == TOCADOS
        assert not any(row[-1] for row in audit)

    def test_aplicar_reverter_duas_vezes(self):
        for _ in range(2):
            result = _run_migrate("migrate", "--yes")
            assert result.returncode == 0, result.stdout + result.stderr
            assert _news_codes() == ESPERADO_APOS_034
            result = _run_migrate("rollback", "034", "--yes")
            assert result.returncode == 0, result.stdout + result.stderr
            assert _news_codes() == CORPUS
        assert len(_audit()) == len(TOCADOS)
        assert _campanhas() == {"tema26-034"}


@pytest.mark.integration
class TestContratoComODs1:
    """O preflight do DS-1 (data-science#49) aceita a tabela que a 034 cria."""

    def test_colunas_do_contrato(self):
        _run_migrate("migrate", "--yes")
        colunas = {
            row[0] for row in _execute_params(DS1_AUDIT_COLUMNS_SQL, ("news_theme_changes",))
        }
        assert set(DS1_AUDIT_REQUIRED_COLUMNS) <= colunas

    def test_unique_campaign_unique_id_sem_predicado(self):
        _run_migrate("migrate", "--yes")
        assert _execute_params(DS1_AUDIT_UNIQUE_SQL, ("news_theme_changes",)) == [(True,)]

    def test_colunas_tipos_e_nulidade_exatamente_do_contrato(self):
        _run_migrate("migrate", "--yes")
        colunas = _execute(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns WHERE table_name = 'news_theme_changes' "
            "ORDER BY ordinal_position"
        )
        codigos = [
            (f"{lado}_{nivel}_code", "character varying", 20, "YES")
            for lado in ("old", "new")
            for nivel in ("l1", "l2", "l3", "most_specific")
        ]
        assert colunas == [
            ("id", "bigint", None, "NO"),
            ("campaign", "character varying", 50, "NO"),
            ("unique_id", "character varying", 120, "NO"),
            *codigos,
            ("source", "character varying", 50, "NO"),
            ("note", "text", None, "YES"),
            ("changed_at", "timestamp with time zone", None, "NO"),
            ("reverted_at", "timestamp with time zone", None, "YES"),
        ]

    def test_unique_e_constraint_da_tabela(self):
        _run_migrate("migrate", "--yes")
        assert _execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'news_theme_changes'::regclass AND contype = 'u'"
        ) == [("uq_news_theme_changes_campaign_uid", "UNIQUE (campaign, unique_id)")]

    def test_tabela_pre_existente_sem_unique_aborta(self, mod):
        _execute(
            "CREATE TABLE news_theme_changes (id BIGSERIAL PRIMARY KEY, "
            "campaign VARCHAR(50) NOT NULL, unique_id VARCHAR(120) NOT NULL)"
        )
        with pytest.raises(RuntimeError, match="UNIQUE"):
            _run_module(mod, "migrate", dry_run=False)
        assert _news_codes() == CORPUS

    def test_campanha_do_llm_sem_fonte_estranha(self):
        _run_migrate("migrate", "--yes")
        assert _execute_params(DS1_CAMPAIGN_FOREIGN_SOURCES_SQL, (LLM_CAMPAIGN, "llm:%")) == []
        estranhas = _execute_params(DS1_CAMPAIGN_FOREIGN_SOURCES_SQL, ("tema26-034", "llm:%"))
        assert estranhas == [("migration-034",)]

    def test_unique_barra_segunda_linha_do_mesmo_artigo_na_campanha(self):
        _run_migrate("migrate", "--yes")
        novo = ("26", "26.01", "26.01.03", "26.01.03")
        _log_audit("inc_esd", ESPERADO_APOS_034["inc_esd"], novo)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _log_audit("inc_esd", novo, novo)


@pytest.mark.integration
class TestMergeDoBigQueryLeAsCampanhas:
    """bq-merge-theme-changes lê o estado atual dos artigos de todas as campanhas tema26-*."""

    def test_campanhas_padrao_incluem_a_do_llm(self):
        from data_platform.jobs.bigquery import theme_changes

        _run_migrate("migrate", "--yes")
        _d1_llm()

        df = theme_changes.fetch_theme_changes_state(DATABASE_URL, theme_changes.DEFAULT_CAMPAIGNS)

        assert set(df["unique_id"]) == TOCADOS | {"clima", "militar"}
        clima = df.set_index("unique_id").loc["clima"]
        assert clima["theme_l1_code"] == "26"
        assert clima["most_specific_theme_code"] == "26.02.01"

    def test_contagem_por_campanha(self):
        from data_platform.jobs.bigquery import theme_changes

        _run_migrate("migrate", "--yes")
        _d1_llm()

        contagem = theme_changes.count_by_campaign(DATABASE_URL, theme_changes.DEFAULT_CAMPAIGNS)

        assert contagem == {"tema26-034": len(TOCADOS), LLM_CAMPAIGN: 3}
