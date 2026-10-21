"""Unit tests for feature computation functions."""

import unicodedata
from datetime import UTC, datetime

import pyphen
import pytest

from data_platform.workers.feature_worker.features import (
    compute_all,
    compute_char_count,
    compute_content_annotations,
    compute_has_image,
    compute_has_video,
    compute_paragraph_count,
    compute_publication_dow,
    compute_publication_hour,
    compute_readability_flesch,
    compute_readability_flesch_ptbr,
    compute_word_count,
    count_syllables_ptbr,
    readability_counts_ptbr,
)


class TestComputeWordCount:
    def test_normal_text(self):
        assert compute_word_count("Hello world foo bar") == 4

    def test_empty_content(self):
        assert compute_word_count(None) == 0
        assert compute_word_count("") == 0

    def test_multiline(self):
        assert compute_word_count("Hello\nworld\nfoo") == 3


class TestComputeCharCount:
    def test_normal_text(self):
        assert compute_char_count("Hello") == 5

    def test_empty(self):
        assert compute_char_count(None) == 0
        assert compute_char_count("") == 0


class TestComputeParagraphCount:
    def test_single_paragraph(self):
        assert compute_paragraph_count("One paragraph") == 1

    def test_multiple_paragraphs(self):
        assert compute_paragraph_count("First\n\nSecond\n\nThird") == 3

    def test_empty(self):
        assert compute_paragraph_count(None) == 0
        assert compute_paragraph_count("") == 0

    def test_blank_paragraphs_ignored(self):
        assert compute_paragraph_count("First\n\n\n\nSecond") == 2


class TestComputeHasImage:
    def test_with_url(self):
        assert compute_has_image("https://example.com/img.jpg") is True

    def test_without_url(self):
        assert compute_has_image(None) is False
        assert compute_has_image("") is False


class TestComputeHasVideo:
    def test_with_url(self):
        assert compute_has_video("https://example.com/vid.mp4") is True

    def test_without_url(self):
        assert compute_has_video(None) is False
        assert compute_has_video("") is False


class TestComputePublicationHour:
    def test_utc_hour(self):
        dt = datetime(2024, 6, 15, 14, 30, 0, tzinfo=UTC)
        assert compute_publication_hour(dt) == 14

    def test_midnight(self):
        dt = datetime(2024, 6, 15, 0, 0, 0, tzinfo=UTC)
        assert compute_publication_hour(dt) == 0

    def test_none_raises(self):
        """None input raises AttributeError — callers must guard with `if published_at`."""
        with pytest.raises(AttributeError):
            compute_publication_hour(None)


class TestComputePublicationDow:
    def test_monday(self):
        dt = datetime(2024, 6, 17, 12, 0, 0)  # Monday
        assert compute_publication_dow(dt) == 0

    def test_sunday(self):
        dt = datetime(2024, 6, 16, 12, 0, 0)  # Sunday
        assert compute_publication_dow(dt) == 6

    def test_none_raises(self):
        """None input raises AttributeError — callers must guard with `if published_at`."""
        with pytest.raises(AttributeError):
            compute_publication_dow(None)


class TestComputeReadabilityFlesch:
    def test_normal_text(self):
        text = "Este é um texto simples em português. " * 5
        result = compute_readability_flesch(text)
        assert result is not None
        assert isinstance(result, float)

    def test_empty_content(self):
        assert compute_readability_flesch(None) is None
        assert compute_readability_flesch("") is None

    def test_short_text(self):
        assert compute_readability_flesch("Curto") is None

    # Escala fixada: fórmula inglesa do textstat 0.7.13 (206,835 − 1,015·ASL −
    # 84,6·ASW), sem set_lang. Não é a adaptação pt-BR (Martins/1996) e pode dar
    # negativo. Se este valor mudar (set_lang('pt') acidental, troca de versão do
    # textstat/pyphen), a série histórica de readability_flesch deixa de ser
    # comparável: crie uma chave nova (ex.: readability_flesch_ptbr) em vez de
    # alterar esta.
    _FRASE_CURTA = (
        "O Ministério da Educação anunciou nesta segunda-feira a ampliação do "
        "programa de bolsas para estudantes de baixa renda em todo o país."
    )
    _FRASE_LONGA = (
        "A Secretaria de Comunicação Social da Presidência da República informa que "
        "as inscrições para o processo seletivo simplificado de contratação temporária "
        "de profissionais especializados estarão abertas a partir da próxima semana, "
        "conforme os critérios estabelecidos no edital."
    )

    def test_flesch_formula_inglesa_fixada(self):
        assert compute_readability_flesch(self._FRASE_CURTA) == 38.38

    def test_flesch_ingles_pode_ser_negativo_em_pt(self):
        assert compute_readability_flesch(self._FRASE_LONGA) == -15.93


class TestComputeReadabilityFleschPtbr:
    """Adaptação de Martins et al. (1996): 248,835 − 1,015·ASL − 84,6·ASW.

    Sílabas pelo pyphen pt_BR (left=1, right=1): pontos de hifenização + 1. Mesmas
    frases do teste inglês, para comparar as escalas: a contagem pt_BR acha mais
    sílabas que a inglesa (50 vs 38 na frase curta), o que anula boa parte dos +42
    da constante. Se um valor fixado mudar (troca de versão do pyphen/dicionário),
    a série histórica deixa de ser comparável: suba a versão no feature_registry.
    """

    _FRASE_CURTA = TestComputeReadabilityFlesch._FRASE_CURTA
    _FRASE_LONGA = TestComputeReadabilityFlesch._FRASE_LONGA

    def test_dicionario_pt_br_disponivel_no_pyphen(self):
        assert "pt_BR" in pyphen.LANGUAGES

    def test_contagens_da_frase_curta(self):
        # 22 palavras (segunda-feira conta 1), 1 frase, 50 sílabas
        assert readability_counts_ptbr(self._FRASE_CURTA) == (22, 1, 50)

    def test_contagens_da_frase_longa(self):
        assert readability_counts_ptbr(self._FRASE_LONGA) == (37, 1, 103)

    def test_flesch_ptbr_fixado_frase_curta(self):
        assert compute_readability_flesch_ptbr(self._FRASE_CURTA) == 34.23
        assert compute_readability_flesch_ptbr(self._FRASE_CURTA) == round(
            248.835 - 1.015 * 22 / 1 - 84.6 * 50 / 22, 2
        )

    def test_flesch_ptbr_fixado_frase_longa_sem_clamp(self):
        """Valor cru: pode sair de [0, 100] (aqui, negativo)."""
        assert compute_readability_flesch_ptbr(self._FRASE_LONGA) == -24.23

    def test_pode_passar_de_100(self):
        texto = "O sol é bom. A paz é boa. O mar é azul. A luz é bela."
        assert compute_readability_flesch_ptbr(texto) > 100

    def test_vazio_e_curto_retornam_none(self):
        assert compute_readability_flesch_ptbr(None) is None
        assert compute_readability_flesch_ptbr("") is None
        assert compute_readability_flesch_ptbr("Curto") is None

    def test_limite_de_10_palavras(self):
        nove = "um dois três quatro cinco seis sete oito nove."
        assert compute_readability_flesch_ptbr(nove) is None
        assert isinstance(compute_readability_flesch_ptbr(nove + " dez"), float)

    def test_numeros_nao_contam_como_palavras(self):
        """10 tokens, mas só 9 palavras alfabéticas: None."""
        texto = "Foram 2026 vagas para estudantes de baixa renda no país."
        assert compute_readability_flesch_ptbr(texto) is None


class TestReadabilityCountsPtbr:
    """Tokenização da versão pt-BR: (palavras, frases, sílabas)."""

    def test_palavra_composta_com_hifen_conta_uma_e_soma_silabas(self):
        assert readability_counts_ptbr("segunda-feira") == (1, 1, 5)

    def test_palavras_acentuadas_sao_alfabeticas(self):
        assert readability_counts_ptbr("ação é já")[0] == 3

    def test_frases_por_pontuacao_seguida_de_espaco_ou_fim(self):
        texto = "Primeira frase. Segunda frase! Terceira frase? Quarta… Quinta"
        assert readability_counts_ptbr(texto)[1] == 5

    def test_ponto_dentro_de_numero_nao_quebra_frase(self):
        texto = "Foram R$ 259.973,41 e 1.500 vagas em 2,5 meses."
        assert readability_counts_ptbr(texto)[1] == 1

    def test_aspas_e_parenteses_de_fechamento_apos_o_ponto(self):
        texto = 'Ele disse: "Vamos." Depois saiu (sem pressa.) E voltou.'
        assert readability_counts_ptbr(texto)[1] == 3

    def test_linha_em_branco_separa_titulo_sem_ponto(self):
        texto = "Título sem ponto\n\nPrimeira frase aqui. Segunda frase"
        assert readability_counts_ptbr(texto)[1] == 3

    def test_linha_so_com_espacos_conta_como_branca(self):
        assert readability_counts_ptbr("Linha um  \n  \nLinha dois")[1] == 2

    def test_itens_de_lista_e_titulos_markdown_separam_frases(self):
        texto = "Itens do edital\n- primeiro item\n* segundo item\n1. terceiro item\n## Serviço\nDetalhes"
        assert readability_counts_ptbr(texto)[1] == 6

    def test_quebra_de_linha_simples_nao_separa_frase(self):
        assert readability_counts_ptbr("uma frase que\ncontinua aqui")[1] == 1

    def test_link_markdown_conta_so_o_texto(self):
        texto = "[Leia o edital](https://www.gov.br/mec/pt-br/edital-final.pdf) agora."
        assert readability_counts_ptbr(texto)[:2] == (4, 1)

    def test_imagem_markdown_e_ignorada(self):
        texto = "![Foto do ministro durante o evento](https://www.gov.br/foto.jpg)\n\nTexto."
        assert readability_counts_ptbr(texto)[:2] == (1, 1)

    def test_url_solta_e_ignorada_e_preserva_o_ponto_final(self):
        texto = "Acesse https://www.gov.br/mec/pt-br. Depois www.inep.gov.br/enem, hoje."
        assert readability_counts_ptbr(texto)[:2] == (3, 2)

    def test_texto_sem_palavras(self):
        assert readability_counts_ptbr("2026 — 10/10.") == (0, 0, 0)


class TestCountSyllablesPtbr:
    """Gold list do método (pyphen pt_BR, left=1, right=1; pontos + 1).

    Reflete o que o método produz. Desvios conhecidos da divisão silábica
    gramatical estão anotados (gramática entre parênteses): hiatos que o
    dicionário não separa (saúde, baú, juiz, rainha), ditongos finais tratados
    como hiato (anunciou) e encontro consonantal inicial separado por left=1 (pneu).
    """

    GOLD = {
        "a": 1,
        "é": 1,
        "de": 1,
        "mãe": 1,
        "pão": 1,
        "país": 2,
        "água": 2,
        "dia": 2,
        "guerra": 2,
        "quatro": 2,
        "também": 2,
        "leão": 2,
        "voo": 2,
        "saúde": 2,  # desvio (sa-ú-de = 3)
        "baú": 1,  # desvio (ba-ú = 2)
        "juiz": 1,  # desvio (ju-iz = 2)
        "rainha": 2,  # desvio (ra-i-nha = 3)
        "ciência": 2,  # desvio (ci-ên-cia = 3)
        "pneu": 2,  # desvio (pneu = 1)
        "países": 3,
        "saída": 3,
        "juízes": 3,
        "teatro": 3,
        "poeta": 3,
        "coração": 3,
        "eleição": 3,
        "frequência": 3,
        "ônibus": 3,
        "Brasília": 3,
        "enjoo": 3,
        "ministério": 4,
        "educação": 4,
        "violência": 4,
        "caatinga": 4,
        "qualidade": 4,
        "anunciou": 4,  # desvio (a-nun-ciou = 3)
        "cooperação": 5,
        "psicologia": 5,
        "profissionais": 5,
        "Secretaria": 5,
        "especializados": 7,
        "sustentabilidade": 7,
    }

    @pytest.mark.parametrize(("word", "expected"), sorted(GOLD.items()))
    def test_gold(self, word, expected):
        assert count_syllables_ptbr(word) == expected

    @pytest.mark.parametrize(
        ("word", "expected"),
        [("segunda-feira", 5), ("pós-graduação", 5), ("bem-estar", 3), ("guarda-chuva", 4)],
    )
    def test_hifenizada_soma_as_partes(self, word, expected):
        assert count_syllables_ptbr(word) == expected

    def test_maiusculas_contam_igual(self):
        assert count_syllables_ptbr("EDUCAÇÃO") == count_syllables_ptbr("educação") == 4

    def test_minimo_uma_silaba_por_palavra(self):
        assert count_syllables_ptbr("x") == 1


class TestComputeAll:
    def test_complete_article(self):
        article = {
            "content": "Este é o conteúdo do artigo. " * 5,
            "image_url": "https://example.com/img.jpg",
            "video_url": None,
            "published_at": datetime(2024, 6, 17, 14, 30, 0, tzinfo=UTC),
        }
        features = compute_all(article)

        assert features["word_count"] > 0
        assert features["char_count"] > 0
        assert features["paragraph_count"] >= 1
        assert features["has_image"] is True
        assert features["has_video"] is False
        assert features["publication_hour"] == 14
        assert features["publication_dow"] == 0  # Monday

    def test_minimal_article(self):
        article = {"content": None, "image_url": None, "video_url": None}
        features = compute_all(article)

        assert features["word_count"] == 0
        assert features["has_image"] is False
        assert "publication_hour" not in features
        assert "readability_flesch" not in features
        assert "readability_flesch_ptbr" not in features

    def test_flesch_ptbr_ao_lado_do_ingles(self):
        """Chave nova; readability_flesch (inglês) segue com o mesmo valor."""
        content = TestComputeReadabilityFlesch._FRASE_CURTA
        features = compute_all({"content": content, "image_url": None, "video_url": None})

        assert features["readability_flesch"] == 38.38
        assert features["readability_flesch_ptbr"] == 34.23

    def test_explicit_none_published_at(self):
        """Explicit published_at=None behaves same as missing key."""
        article = {
            "content": "Some text.",
            "image_url": None,
            "video_url": None,
            "published_at": None,
        }
        features = compute_all(article)

        assert "publication_hour" not in features
        assert "publication_dow" not in features


class TestComputeContentAnnotations:
    """Tests for compute_content_annotations() — deterministic offset derivation."""

    def test_simple_single_occurrence(self):
        content = "O MEC anunciou novidades."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}]
        result = compute_content_annotations(content, entities)
        assert result == [
            {"start": 2, "end": 5, "type": "ORG", "text": "MEC", "canonical_id": "dgb_mec"}
        ]
        # Verify the slice matches the original surface exactly.
        assert content[2:5] == "MEC"

    def test_nested_overlap_longest_match_wins(self):
        """'Ministério da Educação (MEC)' engulfs the nested 'MEC'; a later
        standalone 'MEC' still matches."""
        content = "O Ministério da Educação (MEC) agiu. Depois o MEC voltou."
        entities = [
            {"text": "Ministério da Educação (MEC)", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
        ]
        result = compute_content_annotations(content, entities)
        # First span = the long surface; the nested MEC inside it is dropped.
        long_start = content.index("Ministério da Educação (MEC)")
        long_end = long_start + len("Ministério da Educação (MEC)")
        standalone_start = content.index("MEC", long_end)
        assert result == [
            {
                "start": long_start,
                "end": long_end,
                "type": "ORG",
                "text": "Ministério da Educação (MEC)",
                "canonical_id": "dgb_mec",
            },
            {
                "start": standalone_start,
                "end": standalone_start + 3,
                "type": "ORG",
                "text": "MEC",
                "canonical_id": "dgb_mec",
            },
        ]

    def test_multiple_occurrences_all_marked(self):
        content = "Lula falou. Lula repetiu. Lula concluiu."
        entities = [{"text": "Lula", "type": "PER", "canonical_id": "Q8765"}]
        result = compute_content_annotations(content, entities)
        starts = [a["start"] for a in result]
        assert starts == [0, 12, 26]
        for a in result:
            assert content[a["start"] : a["end"]] == "Lula"

    def test_accent_and_case_insensitive_preserves_offsets(self):
        """Match is accent/case-insensitive but offsets/text reflect the original."""
        content = "A EDUCACAO e a educação importam."
        entities = [{"text": "Educação", "type": "POLICY", "canonical_id": None}]
        result = compute_content_annotations(content, entities)
        # Both 'EDUCACAO' (no accent, uppercase) and 'educação' (lowercase, accent) match.
        assert len(result) == 2
        first, second = result
        assert content[first["start"] : first["end"]] == "EDUCACAO"
        assert content[second["start"] : second["end"]] == "educação"
        assert first["type"] == "POLICY"
        assert first["canonical_id"] is None

    def test_nfd_content_offsets_index_original_string(self):
        """REGRESSION: NFD (decomposed) content must yield offsets that slice the
        ORIGINAL string correctly. NFC normalization is NOT length-preserving, so
        the previous equal-length assumption corrupted offsets after the first
        decomposed accent (INSS sliced to ' INS')."""
        content = unicodedata.normalize("NFD", "No Ministério da Saúde, o INSS agiu.")
        # Sanity: the fixture really is decomposed (not already NFC).
        assert content != unicodedata.normalize("NFC", content)
        entities = [{"text": "INSS", "type": "ORG", "canonical_id": "dgb_inss"}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert content[result[0]["start"] : result[0]["end"]] == "INSS"
        assert result[0]["text"] == "INSS"

    def test_nfd_accented_entity_in_nfd_content(self):
        """Accented surface matched in NFD content returns the correct original
        (decomposed) slice — offsets index the original, not a renormalized copy."""
        content = unicodedata.normalize("NFD", "O Ministério da Saúde divulgou dados.")
        assert content != unicodedata.normalize("NFC", content)
        entities = [{"text": "Saúde", "type": "ORG", "canonical_id": "dgb_ms"}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        start, end = result[0]["start"], result[0]["end"]
        # The slice equals 'Saúde' under NFC comparison (it is the NFD form here).
        assert unicodedata.normalize("NFC", content[start:end]) == "Saúde"
        assert result[0]["text"] == content[start:end]

    def test_fold_expansion_maps_back_to_original_span(self):
        """A surface whose fold EXPANDS the source (ß → ss) still maps its span
        back to the original (shorter) codepoints — index map handles contraction."""
        content = "Die Straße ist hier."
        entities = [{"text": "Strasse", "type": "LOC", "canonical_id": None}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert content[result[0]["start"] : result[0]["end"]] == "Straße"

    def test_word_boundary_prevents_substring_match(self):
        """'MEC' must not match inside 'MECANICA' or 'COMEÇO'."""
        content = "A MECANICA do COMEÇO. Mas o MEC sim."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": None}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert content[result[0]["start"] : result[0]["end"]] == "MEC"

    def test_internal_whitespace_collapsed(self):
        """Multiple spaces / newlines in content between surface words still match."""
        content = "O Ministério   da\nEducação cresceu."
        entities = [{"text": "Ministério da Educação", "type": "ORG", "canonical_id": "dgb_mec"}]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        # `text` reflects the ORIGINAL slice (with the real whitespace run).
        assert result[0]["text"] == "Ministério   da\nEducação"
        assert content[result[0]["start"] : result[0]["end"]] == "Ministério   da\nEducação"

    def test_surface_not_in_content_skipped_silently(self):
        content = "Texto sobre saúde pública."
        entities = [
            {"text": "Bolsa Família", "type": "POLICY", "canonical_id": "dgb_bf"},
            {"text": "saúde", "type": "POLICY", "canonical_id": None},
        ]
        result = compute_content_annotations(content, entities)
        # Only 'saúde' is present.
        assert len(result) == 1
        assert result[0]["text"] == "saúde"

    def test_output_is_flat_sorted_non_overlapping(self):
        content = "Brasília recebeu Lula e o MEC na quarta."
        entities = [
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "Lula", "type": "PER", "canonical_id": "Q8765"},
            {"text": "Brasília", "type": "LOC", "canonical_id": "Q2844"},
        ]
        result = compute_content_annotations(content, entities)
        starts = [a["start"] for a in result]
        assert starts == sorted(starts)
        # No overlap.
        for prev, nxt in zip(result, result[1:], strict=False):
            assert prev["end"] <= nxt["start"]

    def test_idempotent_same_input_same_output(self):
        content = "O Ministério da Educação (MEC) e o MEC."
        entities = [
            {"text": "Ministério da Educação (MEC)", "type": "ORG", "canonical_id": "dgb_mec"},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"},
        ]
        first = compute_content_annotations(content, entities)
        second = compute_content_annotations(content, entities)
        assert first == second

    def test_empty_entities_returns_empty(self):
        assert compute_content_annotations("Algum texto.", []) == []

    def test_empty_content_returns_empty(self):
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": None}]
        assert compute_content_annotations("", entities) == []
        assert compute_content_annotations(None, entities) == []

    def test_tie_break_equal_span_by_count_then_order(self):
        """When two entities match the exact same span, higher count wins."""
        content = "O MEC agiu."
        entities = [
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_a", "count": 1},
            {"text": "MEC", "type": "ORG", "canonical_id": "dgb_b", "count": 9},
        ]
        result = compute_content_annotations(content, entities)
        assert len(result) == 1
        assert result[0]["canonical_id"] == "dgb_b"

    def test_missing_canonical_id_defaults_null(self):
        content = "O MEC agiu."
        entities = [{"text": "MEC", "type": "ORG"}]
        result = compute_content_annotations(content, entities)
        assert result[0]["canonical_id"] is None
