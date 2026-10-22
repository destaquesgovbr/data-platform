"""Testes da chave de quase-duplicata (jobs/graph/content_keys.py, regra H5 do DP-1b).

Os casos seguem o relatório ~/dgb-runs/dedup_near_dup_report_2026-10-21.md (§5 e §6). Os textos
são sintéticos (tokens numerados) para fixar a similaridade de cada par: cada caso confere o
regime (J, C) com as próprias funções do módulo antes de afirmar o agrupamento.
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.graph import content_keys as ck
from data_platform.jobs.graph.content_keys import (
    ArticleRow,
    clean_markdown,
    content_words,
    is_usable,
    normalize_text,
    plan_content_keys,
    shingle_set,
    similarity,
    slot_variant,
    title_eligible,
)

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
MIGRATION_010 = (
    Path(__file__).resolve().parents[4] / "scripts" / "migrations" / "010_backfill_content_hash.py"
)

LOGIN_WALL = (
    "É necessário autenticar para visualizar este conteúdo. Faça login com a sua conta gov.br "
    "para continuar a leitura desta página e acessar os demais serviços do portal institucional "
    "do órgão responsável pela publicação."
)


def _p(prefixo: str, inicio: int, fim: int) -> list[str]:
    return [f"{prefixo}{i}" for i in range(inicio, fim)]


def _t(*partes: list[str]) -> str:
    return " ".join(w for parte in partes for w in parte)


def _row(uid, agency, title, content, horas=0.0, key=None) -> ArticleRow:
    return ArticleRow(uid, title, content, agency, T0 + timedelta(hours=horas), key)


def _plan(*rows, since=None, until=None):
    ordered = sorted(rows, key=lambda r: (r.published_at, r.unique_id))
    return plan_content_keys(ordered, since=since, until=until)


def _keys(*rows) -> dict:
    return _plan(*rows).keys


def _js(a: str, b: str) -> tuple[float, float, int]:
    return similarity(shingle_set(content_words(a)), shingle_set(content_words(b)))


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


class TestNormalizacao:
    def test_clean_markdown_remove_imagens_e_urls_e_mantem_texto_do_link(self):
        texto = (
            "Veja ![Foto: Ascom](https://www.gov.br/inss/img/a.jpg) o "
            "[edital completo](https://www.gov.br/mec/edital.pdf) em https://www.gov.br/mec "
            "ou www.mec.gov.br."
        )

        assert content_words(texto) == ["veja", "o", "edital", "completo", "em", "ou"]
        assert "https" not in clean_markdown(texto)
        assert "Foto" not in clean_markdown(texto)

    def test_clean_markdown_de_vazio(self):
        assert clean_markdown(None) == ""
        assert clean_markdown("") == ""

    @pytest.mark.parametrize(
        "texto",
        ["Ação É Já!", "  São   Paulo\n\tRJ ", "Pé-de-Meia: R$ 1.000,00 (março)", "", None],
    )
    def test_normalize_text_igual_ao_da_migracao_010(self, texto):
        spec = importlib.util.spec_from_file_location("migration_010", MIGRATION_010)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert normalize_text(texto) == module.normalize_text(texto)

    def test_normalize_text_ascii_minusculas_sem_pontuacao(self):
        assert normalize_text("  INSS bate RECORDE: 890 mil — no mês!  ") == (
            "inss bate recorde 890 mil no mes"
        )

    def test_shingles_de_5_palavras(self):
        palavras = _p("w", 0, 7)

        assert len(shingle_set(palavras)) == 3
        assert shingle_set(palavras) == shingle_set(list(palavras))
        assert shingle_set(palavras[:5]) < shingle_set(palavras)

    def test_texto_com_menos_de_5_palavras_vira_um_shingle(self):
        assert len(shingle_set(["a", "b", "c"])) == 1
        assert shingle_set([]) == frozenset()

    def test_conteudo_utilizavel_tem_ao_menos_30_palavras(self):
        assert not is_usable(_p("w", 0, 29))
        assert is_usable(_p("w", 0, 30))

    def test_tela_de_login_nas_primeiras_20_palavras_nao_e_utilizavel(self):
        assert not is_usable(content_words(LOGIN_WALL + " " + _t(_p("w", 0, 40))))
        assert is_usable(content_words(_t(_p("w", 0, 20)) + " " + LOGIN_WALL))

    def test_similaridade_jaccard_contencao_e_menor_lado(self):
        a = frozenset(range(10))
        b = frozenset(range(5, 25))

        assert similarity(a, b) == (5 / 25, 5 / 10, 10)
        assert similarity(a, frozenset()) == (0.0, 0.0, 0)


class TestTituloElegivelParaE2:
    @pytest.mark.parametrize(
        "titulo",
        [
            "inss bate recorde historico de concessao",
            "mec sergipe acompanha avanco do censo",
        ],
    )
    def test_elegivel(self, titulo):
        assert title_eligible(titulo)

    @pytest.mark.parametrize(
        "titulo",
        [
            "nota a imprensa",  # < 4 tokens (e na lista)
            "nota oficial",
            "nota de pesar",
            "participacoes sociais em andamento",
            "eleicoes 2026 acompanhe a agenda dos candidatos a presidencia",
            "beneficiarios com nis de final 5 recebem o bolsa familia",
            "pedemeia alunos recebem parcela de outubro",
            "",
        ],
    )
    def test_nao_elegivel(self, titulo):
        assert not title_eligible(titulo)


class TestTrocaDeSlot:
    def test_um_token_trocado_e_slot(self):
        assert slot_variant(
            "beneficiarios com nis de final 5 recebem o bolsa familia",
            "beneficiarios com nis de final 6 recebem o bolsa familia",
        )

    def test_uf_trocada_no_inicio_e_slot(self):
        assert slot_variant(
            "sergipe acompanha avanco do censo escolar 2026",
            "bahia acompanha avanco do censo escolar 2026",
        )

    def test_titulos_iguais_nao_sao_slot(self):
        assert not slot_variant("a b c d", "a b c d")

    def test_trecho_com_emissor_nao_e_slot(self):
        """secom/planalto reescrevem o emissor no título: não é variante de modelo."""
        assert not slot_variant(
            "governo federal lanca campanha de vacinacao",
            "ministerio da saude lanca campanha de vacinacao",
        )

    def test_trecho_maior_que_5_tokens_nao_e_slot(self):
        assert not slot_variant(
            "programa amplia atendimento em todo o estado do norte do pais",
            "programa um dois tres quatro cinco seis do norte do pais",
        )

    def test_pouco_prefixo_e_sufixo_em_comum_nao_e_slot(self):
        assert not slot_variant("a b c d e f", "a x y z w f")

    def test_trocas_proximas_formam_um_trecho_so(self):
        """O trecho é contíguo de ponta a ponta: duas trocas a ≤ 5 tokens contam como um slot."""
        assert slot_variant(
            "nis de final 5 recebem nesta terca o beneficio",
            "nis de final 6 recebem nesta quarta o beneficio",
        )

    def test_trocas_distantes_nao_sao_slot(self):
        assert not slot_variant(
            "nis de final 5 recebem o beneficio do programa nesta terca",
            "nis de final 6 recebem o beneficio do programa nesta quarta",
        )


# ---------------------------------------------------------------------------
# Casos do relatório (§5)
# ---------------------------------------------------------------------------

BASE = _p("reforma", 0, 200)
TITULO_INSS = "Governo Federal reduz para 30 dias o prazo de análise de benefícios"


class TestRepublicacaoEntreOrgaos:
    def test_cadeia_limpa_com_urls_diferentes_junta_no_mais_antigo(self):
        """casacivil → previdencia → inss: o content_hash difere só pelas URLs de cada órgão."""
        casacivil = f"![Foto](https://www.gov.br/casacivil/a.jpg)\n{_t(BASE)}"
        previdencia = (
            f"![Foto: Ascom](https://www.gov.br/previdencia/b.jpg)\n{_t(BASE)}\n"
            "[Saiba mais](https://www.gov.br/previdencia/noticias)"
        )
        inss = f"{_t(BASE)}\n![](https://www.gov.br/inss/c.png)"
        assert _js(casacivil, inss)[0] == 1.0
        assert _js(casacivil, previdencia)[0] > 0.97

        keys = _keys(
            _row("casacivil-1", "casacivil", TITULO_INSS, casacivil, 0),
            _row("previdencia-1", "previdencia", TITULO_INSS, previdencia, 0.5),
            _row("inss-1", "inss", TITULO_INSS, inss, 1),
        )

        assert keys == {
            "casacivil-1": "casacivil-1",
            "previdencia-1": "casacivil-1",
            "inss-1": "casacivil-1",
        }

    def test_titulo_reescrito_com_conteudo_quase_igual(self):
        inss = _t(BASE)
        previdencia = _t(_p("abertura", 0, 12), BASE[:190])
        j, _, _ = _js(inss, previdencia)
        assert 0.8 <= j < 0.95

        keys = _keys(
            _row("inss-1", "inss", "INSS bate recorde histórico de concessão: 890 mil", inss, 0),
            _row(
                "prev-1",
                "previdencia",
                "Com 890 mil concessões em março, INSS bate recorde histórico",
                previdencia,
                3,
            ),
        )

        assert keys == {"inss-1": "inss-1", "prev-1": "inss-1"}

    def test_republicacao_adaptada_com_orgao_e_titulo_trocados(self):
        """receitafederal → fazenda, Simples Nacional: J 0,5–0,8 em até 3 dias junta."""
        receita = _t(BASE)
        fazenda = _t(BASE[:150], _p("fazenda", 0, 30))
        j, _, _ = _js(receita, fazenda)
        assert 0.5 <= j < 0.8

        keys = _keys(
            _row("rf-1", "receitafederal", "Receita prorroga prazo do Simples Nacional", receita),
            _row(
                "fz-1", "fazenda", "Empresas do Simples ganham mais tempo para aderir", fazenda, 30
            ),
        )

        assert keys == {"rf-1": "rf-1", "fz-1": "rf-1"}

    def test_mesmo_evento_com_releases_diferentes_nao_junta(self):
        """planalto x cidades, '576 moradias em Manaus': J ~0,35 é outro texto."""
        planalto = _t(BASE)
        cidades = _t(BASE[:100], _p("cidades", 0, 100))
        j, c, _ = _js(planalto, cidades)
        assert j < 0.45 and c < 0.8

        keys = _keys(
            _row("pl-1", "planalto", "Presidente entrega 576 moradias em Manaus", planalto),
            _row("ci-1", "cidades", "Manaus recebe novo conjunto habitacional", cidades, 2),
        )

        assert keys == {"pl-1": None, "ci-1": None}

    def test_republicacao_tardia_com_j_alto_junta_ate_7_dias(self):
        casacivil = _t(BASE)
        mec = _t(BASE[:190], _p("mec", 0, 5))
        assert _js(casacivil, mec)[0] >= 0.8

        keys = _keys(
            _row("cc-1", "casacivil", "Programa amplia vagas em escolas", casacivil),
            _row("mec-1", "mec", "MEC detalha ampliação de vagas", mec, 6 * 24),
        )

        assert keys == {"cc-1": "cc-1", "mec-1": "cc-1"}

    def test_j_medio_depois_de_3_dias_nao_junta(self):
        receita = _t(BASE)
        fazenda = _t(BASE[:150], _p("fazenda", 0, 30))
        assert 0.5 <= _js(receita, fazenda)[0] < 0.8

        keys = _keys(
            _row("rf-1", "receitafederal", "Receita prorroga prazo do Simples", receita),
            _row("fz-1", "fazenda", "Empresas do Simples ganham mais tempo", fazenda, 5 * 24),
        )

        assert keys == {"rf-1": None, "fz-1": None}

    def test_texto_identico_depois_de_7_dias_nao_junta(self):
        keys = _keys(
            _row("a", "casacivil", "Programa amplia vagas em escolas", _t(BASE)),
            _row("b", "mec", "MEC detalha ampliação de vagas", _t(BASE), 8 * 24),
        )

        assert keys == {"a": None, "b": None}


class TestTrechoEContencao:
    def test_trecho_com_ao_menos_50_shingles_junta_pela_contencao(self):
        """Nota da COARF por 8 reguladoras; a ANS publicou só um trecho (J baixo, C alto)."""
        completo = _t(_p("coarf", 0, 300))
        trecho = _t(_p("coarf", 100, 175))
        j, c, menor = _js(completo, trecho)
        assert j < 0.3 and c == 1.0 and menor >= 50

        keys = _keys(
            _row("anvisa-1", "anvisa", "Nota conjunta das agências reguladoras", completo),
            _row("ans-1", "ans", "ANS divulga posicionamento sobre a COARF", trecho, 4),
        )

        assert keys == {"anvisa-1": "anvisa-1", "ans-1": "anvisa-1"}

    def test_trecho_curto_com_titulo_diferente_nao_junta(self):
        completo = _t(_p("coarf", 0, 300))
        trecho = _t(_p("coarf", 100, 140))
        assert _js(completo, trecho)[2] < 50

        keys = _keys(
            _row("anvisa-1", "anvisa", "Nota conjunta das agências reguladoras", completo),
            _row("ans-1", "ans", "ANS divulga posicionamento sobre a COARF", trecho, 4),
        )

        assert keys == {"anvisa-1": None, "ans-1": None}

    def test_trecho_curto_com_mesmo_titulo_junta_pelo_titulo(self):
        completo = _t(_p("coarf", 0, 300))
        trecho = _t(_p("coarf", 100, 140))
        j, c, _ = _js(completo, trecho)
        assert j >= 0.1 or c >= 0.3
        titulo = "Nota conjunta das agências reguladoras sobre a COARF"

        keys = _keys(
            _row("anvisa-1", "anvisa", titulo, completo),
            _row("ans-1", "ans", titulo, trecho, 4),
        )

        assert keys == {"anvisa-1": "anvisa-1", "ans-1": "anvisa-1"}


UFS = ("sergipe", "bahia", "piaui")


def _modelo(uf: str) -> str:
    palavras = _p("censo", 0, 300)
    for pos in (50, 120, 190, 260):
        palavras[pos] = uf
    return _t(palavras)


def _titulo_modelo(uf: str) -> str:
    return f"{uf.title()} acompanha avanço do Censo Escolar 2026"


class TestModelosPorUF:
    """Variantes por UF de um mesmo modelo são conteúdos DISTINTOS (decisão de produto, 21/10)."""

    def _familias(self) -> list[ArticleRow]:
        rows = []
        for i, uf in enumerate(UFS):
            rows.append(_row(f"mec-{uf}", "mec", _titulo_modelo(uf), _modelo(uf), i * 0.1))
            rows.append(_row(f"inep-{uf}", "inep", _titulo_modelo(uf), _modelo(uf), 1 + i * 0.1))
        return rows

    def test_variantes_de_ufs_diferentes_nao_juntam(self):
        assert 0.8 <= _js(_modelo("sergipe"), _modelo("bahia"))[0] < 0.95

        keys = _keys(*self._familias())

        # mec-X ↔ inep-X (mesmo título, mesmo texto) é republicação; UFs diferentes não
        assert keys == {
            **{f"mec-{uf}": f"mec-{uf}" for uf in UFS},
            **{f"inep-{uf}": f"mec-{uf}" for uf in UFS},
        }

    def test_republicacao_avulsa_de_outra_uf_nao_entra_na_familia(self):
        """G1: um membro de família e J < 0,95 descarta a aresta (sem a guarda, juntaria)."""
        avulsa = _row(
            "agenciagov-amapa", "agenciagov", _titulo_modelo("amapa"), _modelo("amapa"), 2
        )

        keys = _keys(*self._familias(), avulsa)

        assert keys["agenciagov-amapa"] is None

    def test_republicacao_do_mesmo_texto_com_titulo_reescrito_junta(self):
        """G1: membro de família com J ≥ 0,95 (o mesmo texto) ainda junta."""
        republicada = _row(
            "agenciagov-bahia",
            "agenciagov",
            "Censo Escolar: a Bahia registra avanço",
            _modelo("bahia"),
            2,
        )

        keys = _keys(*self._familias(), republicada)

        assert keys["agenciagov-bahia"] == "mec-bahia"


TITULO_CIN = "Governo do Brasil mobiliza estados para ampliar a emissão da CIN"
UFS_CIN = ("amazonas", "bahia", "ceara", "goias", "para", "parana")


class TestMesmoTituloNoMesmoOrgao:
    """O mesmo título no mesmo órgão não dispensa as guardas (revisão do PR, 22/10).

    Com o título igual, a E1 e a E2 juntavam sem guarda: o G1 só contava irmãos de título
    diferente e o G2 só valia com títulos diferentes. Casos de produção (mar–jun/2026): gestao
    'mobiliza estados... CIN' (6 UFs, J 0,79–0,89, mesmo dia), mdr 'MIDR reconhece a situação de
    emergência em cinco cidades' (29 e 30/04, J 0,69), ans 'Participações sociais em andamento'
    (2,17 dias, J 0,69) e tesouronacional (14 e 15/04, J 0,49). As capturas repetidas do scraper
    (J ≈ 1, ≤ 1 dia) continuam juntando.
    """

    def _cin(self) -> list[ArticleRow]:
        return [
            _row(f"gestao-{uf}", "gestao", TITULO_CIN, _modelo(uf), i * 0.05)
            for i, uf in enumerate(UFS_CIN)
        ]

    def test_variantes_por_uf_com_o_mesmo_titulo_nao_juntam(self):
        """G1: irmão de mesmo título conta quando J < 0,95 (variante, não recaptura)."""
        assert 0.8 <= _js(_modelo("amazonas"), _modelo("bahia"))[0] < 0.95

        keys = _keys(*self._cin())

        assert keys == {f"gestao-{uf}": None for uf in UFS_CIN}

    def test_republicacao_de_uma_variante_com_o_mesmo_titulo_junta_so_a_sua_uf(self):
        republicada = _row("secom-bahia", "secom", TITULO_CIN, _modelo("bahia"), 3)

        keys = _keys(*self._cin(), republicada)

        assert keys == {
            **{f"gestao-{uf}": None for uf in UFS_CIN if uf != "bahia"},
            "gestao-bahia": "gestao-bahia",
            "secom-bahia": "gestao-bahia",
        }

    def test_mesmo_titulo_com_j_medio_nao_junta(self):
        """G2 na E1: mdr com listas de cidades diferentes no mesmo título (J 0,69)."""
        palavras = _p("midr", 0, 300)
        dia1 = _t(palavras)
        dia2 = _t(palavras[:100], _p("cidade", 0, 40), palavras[140:])
        assert 0.5 <= _js(dia1, dia2)[0] < 0.8
        titulo = "MIDR reconhece a situação de emergência em cinco cidades"

        keys = _keys(
            _row("mdr-29", "mdr", titulo, dia1),
            _row("mdr-30", "mdr", titulo, dia2, 20),
        )
        entre_orgaos = _keys(
            _row("mdr-29", "mdr", titulo, dia1),
            _row("secom-30", "secom", titulo, dia2, 20),
        )

        assert keys == {"mdr-29": None, "mdr-30": None}
        assert entre_orgaos == {"mdr-29": "mdr-29", "secom-30": "mdr-29"}

    def test_titulo_generico_no_mesmo_orgao_exige_j_alto_e_ate_1_dia(self):
        """G2 na E1 com título fora da E2: ans 'Participações sociais em andamento'."""
        palavras = _p("ans", 0, 300)
        a = _t(palavras)
        b = _t(palavras[:100], _p("consulta", 0, 40), palavras[140:])
        assert 0.5 <= _js(a, b)[0] < 0.8
        titulo = "Participações sociais em andamento"

        keys = _keys(_row("ans-1", "ans", titulo, a), _row("ans-2", "ans", titulo, b, 52))

        assert keys == {"ans-1": None, "ans-2": None}

    def test_mesmo_titulo_com_j_baixo_nao_junta_pelo_titulo(self):
        """G2 na E2: tesouronacional, comunicados diferentes com o mesmo título (J 0,49)."""
        a = _t(_p("tesouro", 0, 300))
        b = _t(_p("tesouro", 0, 150), _p("leilao", 0, 150))
        assert 0.1 <= _js(a, b)[0] < 0.5
        titulo = "Tesouro Nacional divulga o resultado do leilão de títulos públicos"

        keys = _keys(
            _row("tn-14", "tesouronacional", titulo, a),
            _row("tn-15", "tesouronacional", titulo, b, 22),
        )

        assert keys == {"tn-14": None, "tn-15": None}

    def test_recaptura_editada_com_j_alto_junta(self):
        """Duas capturas do mesmo artigo, editado entre elas (J 0,8–0,95, ≤ 1 dia): junta."""
        primeira = _t(BASE)
        editada = _t(BASE[:190], _p("atualizacao", 0, 10))
        assert 0.8 <= _js(primeira, editada)[0] < 0.95
        titulo = "INSS antecipa pagamento do seguro-defeso a pescadores"

        keys = _keys(
            _row("inss-a", "inss", titulo, primeira),
            _row("inss-b", "inss", titulo, editada, 5),
        )

        assert keys == {"inss-a": "inss-a", "inss-b": "inss-a"}

    def test_tela_de_login_e_recaptura_no_mesmo_orgao_junta_pelo_titulo(self):
        """Sem J (um lado inutilizável), só a E2 decide: as guardas não se aplicam."""
        titulo = "INSS antecipa pagamento do seguro-defeso a pescadores"

        keys = _keys(
            _row("inss-a", "inss", titulo, LOGIN_WALL),
            _row("inss-b", "inss", titulo, _t(BASE), 5),
        )

        assert keys == {"inss-a": "inss-a", "inss-b": "inss-a"}


class TestMesmoOrgao:
    def test_notas_recorrentes_com_troca_de_slot_nao_juntam(self):
        """Agência Brasil 'NIS de final 5/6': J ≥ 0,8 em 1 dia, título só troca o dígito."""
        dia1 = _t(_p("bf", 0, 100), ["5"], _p("bf", 100, 200), ["5"], _p("bf", 200, 300))
        dia2 = _t(_p("bf", 0, 100), ["6"], _p("bf", 100, 200), ["6"], _p("bf", 200, 300))
        assert _js(dia1, dia2)[0] >= 0.8

        keys = _keys(
            _row("ab-5", "agencia_brasil", "Beneficiários com NIS final 5 recebem hoje", dia1),
            _row("ab-6", "agencia_brasil", "Beneficiários com NIS final 6 recebem hoje", dia2, 23),
        )

        assert keys == {"ab-5": None, "ab-6": None}

    def test_mesmo_orgao_com_titulo_reescrito_e_j_alto_junta(self):
        """Agência Brasil com dois títulos no mesmo timestamp (duplicata do scraper)."""
        texto = _t(BASE)

        keys = _keys(
            _row("ab-1", "agencia_brasil", "Governo anuncia novo programa de habitação", texto),
            _row("ab-2", "agencia_brasil", "Minha Casa Minha Vida terá nova faixa", texto),
        )

        assert keys == {"ab-1": "ab-1", "ab-2": "ab-1"}

    def test_mesmo_orgao_exige_j_alto(self):
        """G2: J 0,5–0,8 junta entre órgãos diferentes, mas não no mesmo órgão."""
        a = _t(BASE)
        b = _t(BASE[:150], _p("outro", 0, 30))
        assert 0.5 <= _js(a, b)[0] < 0.8
        titulos = ("Receita prorroga prazo do Simples", "Empresas do Simples ganham mais tempo")

        mesmo = _keys(
            _row("a", "receitafederal", titulos[0], a),
            _row("b", "receitafederal", titulos[1], b, 2),
        )
        outro = _keys(
            _row("a", "receitafederal", titulos[0], a),
            _row("b", "fazenda", titulos[1], b, 2),
        )

        assert mesmo == {"a": None, "b": None}
        assert outro == {"a": "a", "b": "a"}

    def test_mesmo_orgao_exige_ate_1_dia(self):
        texto = _t(BASE)

        keys = _keys(
            _row("a", "agencia_brasil", "Governo anuncia novo programa de habitação", texto),
            _row("b", "agencia_brasil", "Minha Casa Minha Vida terá nova faixa", texto, 30),
        )

        assert keys == {"a": None, "b": None}

    def test_mesmo_titulo_no_mesmo_orgao_junta_capturas_repetidas(self):
        """inss 'pescadores' capturado 3 vezes (03:00, 13:11, 18:04)."""
        titulo = "INSS antecipa pagamento do seguro-defeso a pescadores"
        texto = _t(BASE)

        keys = _keys(
            _row("inss-a", "inss", titulo, texto, 0),
            _row("inss-b", "inss", titulo, texto, 10.2),
            _row("inss-c", "inss", titulo, texto, 15.1),
        )

        assert keys == {"inss-a": "inss-a", "inss-b": "inss-a", "inss-c": "inss-a"}


class TestTituloEConteudoQuebrado:
    def test_telas_de_login_com_titulos_diferentes_nao_juntam(self):
        """MDS e Cultura com tela de login dão J = 1,0 com títulos sem relação."""
        assert _js(LOGIN_WALL, LOGIN_WALL)[0] == 1.0

        keys = _keys(
            _row(
                "mds-1", "mds", "Ministério amplia programa de cisternas no semiárido", LOGIN_WALL
            ),
            _row(
                "cultura-1", "cultura", "Edital de Culturas Populares abre inscrições", LOGIN_WALL
            ),
        )

        assert keys == {"mds-1": None, "cultura-1": None}

    def test_tela_de_login_com_mesmo_titulo_junta_pelo_titulo(self):
        titulo = "Ministério amplia programa de cisternas no semiárido"

        keys = _keys(
            _row("mds-1", "mds", titulo, _t(BASE)),
            _row("secom-1", "secom", titulo, LOGIN_WALL, 20),
        )

        assert keys == {"mds-1": "mds-1", "secom-1": "mds-1"}

    def test_mesmo_titulo_depois_de_2_dias_nao_junta_pelo_titulo(self):
        titulo = "Ministério amplia programa de cisternas no semiárido"

        keys = _keys(
            _row("mds-1", "mds", titulo, _t(BASE)),
            _row("secom-1", "secom", titulo, LOGIN_WALL, 50),
        )

        assert keys == {"mds-1": None, "secom-1": None}

    def test_titulo_generico_nao_junta(self):
        keys = _keys(
            _row("pf-1", "pf", "Nota à imprensa", LOGIN_WALL),
            _row("mdic-1", "mdic", "Nota à imprensa", LOGIN_WALL, 2),
            _row("a-1", "mds", "Participações sociais em andamento", LOGIN_WALL),
            _row("a-2", "mec", "Participações sociais em andamento", LOGIN_WALL, 2),
        )

        assert set(keys.values()) == {None}

    def test_titulo_generico_com_o_mesmo_texto_junta_pelo_conteudo(self):
        """O título genérico só não liga pela E2; texto igual liga pela E1 (sem guardas)."""
        keys = _keys(
            _row("pf-1", "pf", "Nota à imprensa", _t(BASE)),
            _row("mj-1", "mj", "Nota à imprensa", _t(BASE), 2),
        )

        assert keys == {"pf-1": "pf-1", "mj-1": "pf-1"}

    def test_agenda_diaria_com_mesmo_titulo_nao_junta(self):
        """TV Brasil: a agenda diária repete o título e parte do texto (J ≥ 0,1)."""
        titulo = "Eleições 2026: acompanhe a agenda dos candidatos à Presidência"
        dia1 = _t(_p("agenda", 0, 60), _p("dia1_", 0, 140))
        dia2 = _t(_p("agenda", 0, 60), _p("dia2_", 0, 140))
        assert 0.1 <= _js(dia1, dia2)[0] < 0.5

        keys = _keys(
            _row("tv-1", "tvbrasil", titulo, dia1),
            _row("tv-2", "tvbrasil", titulo, dia2, 24),
        )

        assert keys == {"tv-1": None, "tv-2": None}

    def test_mesmo_titulo_com_textos_sem_relacao_nao_junta(self):
        titulo = "Ministério amplia programa de cisternas no semiárido"

        keys = _keys(
            _row("mds-1", "mds", titulo, _t(BASE)),
            _row("secom-1", "secom", titulo, _t(_p("outro", 0, 200)), 2),
        )

        assert keys == {"mds-1": None, "secom-1": None}


# ---------------------------------------------------------------------------
# Agrupamento por líder (§6.4)
# ---------------------------------------------------------------------------


class TestAgrupamentoPorLider:
    def test_estrela_e_nao_componente_conexo(self):
        """A–B e B–C são arestas, A–C não: C não entra no grupo de A (B não é líder)."""
        palavras = _p("w", 0, 320)
        a, b, c = _t(palavras[0:200]), _t(palavras[60:260]), _t(palavras[120:320])
        assert _js(a, b)[0] >= 0.5 and _js(b, c)[0] >= 0.5
        assert _js(a, c)[0] < 0.5 and _js(a, c)[1] < 0.8

        keys = _keys(
            _row("a", "mec", "Título A sobre o programa", a, 0),
            _row("b", "mds", "Título B sobre o programa", b, 1),
            _row("c", "mgi", "Título C sobre o programa", c, 2),
        )

        assert keys == {"a": "a", "b": "a", "c": None}

    def test_escolhe_o_lider_de_maior_jaccard(self):
        titulo = "Programa nacional amplia atendimento nas escolas"
        l1 = _t(_p("x", 0, 200))
        l2 = _t(_p("y", 0, 200))
        u = _t(_p("y", 0, 180), _p("x", 0, 60))
        j1, j2 = _js(u, l1)[0], _js(u, l2)[0]
        assert 0.1 <= j1 < j2

        keys = _keys(
            _row("l1", "mec", titulo, l1, 0),
            _row("l2", "mds", "Outro título sem relação com o primeiro", l2, 1),
            _row("u", "secom", titulo, u, 2),
        )

        assert keys == {"l1": None, "l2": "l2", "u": "l2"}

    def test_grupo_grande_passa_do_limite_de_postings(self):
        """Mais cópias que POSTINGS_CAP: as tardias ainda acham o líder (o mais antigo)."""
        n = ck.POSTINGS_CAP + 10
        rows = [
            _row(f"o{i:03d}", f"orgao{i}", f"Título próprio número {i} do órgão", _t(BASE), i * 0.1)
            for i in range(n)
        ]

        keys = _keys(*rows)

        assert set(keys.values()) == {"o000"}

    def test_janela_desliza_e_esquece_artigos_antigos(self):
        """Cópias diárias: cada uma junta à anterior só enquanto o líder está a ≤ 7 dias."""
        rows = [
            _row(f"d{i:02d}", f"orgao{i}", f"Título próprio número {i} do órgão", _t(BASE), i * 24)
            for i in range(10)
        ]

        keys = _keys(*rows)

        assert {k: v for k, v in keys.items() if v == "d00"} == {
            f"d{i:02d}": "d00" for i in range(8)
        }
        assert keys["d08"] == "d08" and keys["d09"] == "d08"


# ---------------------------------------------------------------------------
# Janela incremental: contexto semeado pela chave gravada, lookahead e escrita mínima
# ---------------------------------------------------------------------------


class TestJanelaIncremental:
    SINCE = T0 + timedelta(days=3)

    def test_artigo_do_contexto_sem_chave_vira_lider_e_ganha_a_chave(self):
        plan = _plan(
            _row("ctx", "casacivil", "Título do contexto", _t(BASE), 2 * 24),
            _row("alvo", "mec", "Título do alvo", _t(BASE), 3 * 24 + 1),
            since=self.SINCE,
        )

        assert plan.keys == {"ctx": "ctx", "alvo": "ctx"}
        assert sorted(plan.changes) == [("alvo", "ctx"), ("ctx", "ctx")]

    def test_membro_do_contexto_nao_e_lider(self):
        """Contexto semeado pela chave gravada: membro de outro grupo não recebe ninguém."""
        plan = _plan(
            _row("ctx", "casacivil", "Título do contexto", _t(BASE), 2 * 24, key="lider_antigo"),
            _row("alvo", "mec", "Título do alvo", _t(BASE), 3 * 24 + 1),
            since=self.SINCE,
        )

        assert plan.keys == {"alvo": None}
        assert plan.changes == []

    def test_contexto_nao_e_regravado(self):
        plan = _plan(
            _row("c1", "casacivil", "Título do contexto", _t(BASE), 1 * 24, key="c1"),
            _row("c2", "mec", "Outro título", _t(BASE), 2 * 24, key="c1"),
            _row("alvo", "mds", "Sem relação nenhuma", _t(_p("z", 0, 200)), 3 * 24 + 1),
            since=self.SINCE,
        )

        assert plan.keys == {"c1": "c1", "alvo": None}
        assert plan.changes == []

    def test_alvo_que_deixou_de_ter_grupo_volta_a_nulo(self):
        plan = _plan(
            _row("alvo", "mec", "Título do alvo", _t(BASE), 3 * 24 + 1, key="velho"),
            since=self.SINCE,
        )

        assert plan.changes == [("alvo", None)]

    def test_lookahead_completa_a_familia_mas_nao_e_gravado(self):
        until = self.SINCE + timedelta(days=1)

        plan = _plan(
            _row("alvo", "mec", "Título do alvo", _t(BASE), 3 * 24 + 1),
            _row("depois", "mds", "Título posterior", _t(BASE), 4 * 24 + 1),
            since=self.SINCE,
            until=until,
        )

        assert plan.keys == {"alvo": "alvo"}
        assert plan.changes == [("alvo", "alvo")]

    def test_idempotente(self):
        rows = [
            _row("a", "casacivil", TITULO_INSS, _t(BASE), 0),
            _row("b", "mec", TITULO_INSS, _t(BASE), 1),
            _row("c", "mds", "Sem relação nenhuma", _t(_p("z", 0, 200)), 2),
        ]
        first = _plan(*rows)
        gravadas = [r._replace(content_key=first.keys[r.unique_id]) for r in rows]

        second = _plan(*gravadas)

        assert first.changes == [("a", "a"), ("b", "a")]
        assert second.keys == first.keys
        assert second.changes == []

    def test_estatisticas(self):
        plan = _plan(
            _row("ctx", "casacivil", "Título do contexto", _t(BASE), 2 * 24),
            _row("alvo", "mec", "Título do alvo", _t(BASE), 3 * 24 + 1),
            _row("curto", "mds", "Texto curto", "poucas palavras", 3 * 24 + 2),
            since=self.SINCE,
        )

        assert plan.stats["read"] == 3
        assert plan.stats["context"] == 1
        assert plan.stats["target"] == 2
        assert plan.stats["unusable"] == 1
        assert plan.stats["edges"] == 1
        assert plan.stats["grouped_target"] == 1
        assert plan.stats["changes"] == 2


# ---------------------------------------------------------------------------
# Banco: leitura, escrita mínima e o job da DAG
# ---------------------------------------------------------------------------


class TestSelectEUpdate:
    def test_select_ordena_por_published_at_e_unique_id(self):
        sql, params = ck.build_select_articles(T0, T0 + timedelta(days=1))

        norm = " ".join(sql.split()).lower()
        assert "from news" in norm
        assert "published_at >= %(start)s" in norm
        assert "published_at < %(end)s" in norm
        assert norm.endswith("order by published_at, unique_id")
        assert params == {"start": T0, "end": T0 + timedelta(days=1)}

    def test_select_sem_limites_le_tudo(self):
        sql, params = ck.build_select_articles(None, None)

        assert "%(start)s" not in sql and "%(end)s" not in sql
        assert params == {}

    def test_update_so_toca_linhas_cuja_chave_muda(self):
        norm = " ".join(ck.UPDATE_CONTENT_KEYS_SQL.split()).lower()

        assert "update news" in norm
        assert "is distinct from" in norm

    def test_janela_de_leitura_inclui_contexto_e_um_dia_para_as_familias(self):
        start, end = ck.read_window(T0, until=None, context_days=7)

        assert start == T0 - timedelta(days=8)
        assert end is None
        assert ck.read_window(None, until=None, context_days=7) == (None, None)

    def test_lookahead_cobre_todo_membro_possivel_do_alvo(self):
        """Membro está a <= 7 dias do líder; +1 dia completa as famílias desses membros. Sem
        isso, um líder no fim do bloco perde o membro na re-execução e alterna NULL/chave."""
        _, end = ck.read_window(T0, until=T0 + timedelta(days=90), context_days=7)

        assert end == T0 + timedelta(days=98)


class TestComputeContentKeys:
    def _conn(self, rows: list[tuple]) -> MagicMock:
        conn = MagicMock()
        stream = MagicMock()
        stream.__iter__.return_value = iter(rows)
        conn.cursor.side_effect = lambda *a, **k: stream if k.get("name") else MagicMock()
        return conn

    def test_grava_so_as_mudancas(self):
        rows = [
            ("a", TITULO_INSS, _t(BASE), "casacivil", T0, None),
            ("b", TITULO_INSS, _t(BASE), "mec", T0 + timedelta(hours=1), "a"),
        ]
        conn = self._conn(rows)

        with patch.object(ck, "_write_changes", return_value=1) as write:
            result = ck.compute_content_keys(conn, since=None)

        write.assert_called_once_with(conn, [("a", "a")])
        assert result["changes"] == 1
        assert result["updated"] == 1

    def test_dry_run_nao_grava(self):
        rows = [
            ("a", TITULO_INSS, _t(BASE), "casacivil", T0, None),
            ("b", TITULO_INSS, _t(BASE), "mec", T0 + timedelta(hours=1), None),
        ]
        conn = self._conn(rows)

        with patch.object(ck, "_write_changes") as write:
            result = ck.compute_content_keys(conn, since=None, dry_run=True)

        write.assert_not_called()
        assert result["changes"] == 2
        assert result["updated"] == 0
        assert result["dry_run"] is True


class TestRunContentKeys:
    def test_recalcula_os_ultimos_10_dias_e_comita(self):
        agora = datetime(2026, 11, 4, 12, tzinfo=UTC)
        conn = MagicMock()

        with (
            patch("psycopg2.connect", return_value=conn) as connect,
            patch.object(ck, "compute_content_keys", return_value={"changes": 0}) as compute,
        ):
            result = ck.run_content_keys("postgresql://u@h/db", now=agora)

        connect.assert_called_once_with("postgresql://u@h/db")
        compute.assert_called_once_with(conn, since=agora - timedelta(days=10))
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        assert result == {"changes": 0}
        assert ck.RECOMPUTE_DAYS == 10

    def test_falha_faz_rollback(self):
        conn = MagicMock()

        with (
            patch("psycopg2.connect", return_value=conn),
            patch.object(ck, "compute_content_keys", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            ck.run_content_keys("postgresql://u@h/db")

        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()
        conn.close.assert_called_once()
