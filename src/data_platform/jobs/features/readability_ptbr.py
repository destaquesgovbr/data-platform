"""Flesch reading ease pt-BR (Martins et al., 1996), sem I/O.

Fica fora do feature-worker para rodar também no Composer (task fill_flesch_ptbr da DAG
aggregate_engagement, DP-1c): só depende do pyphen, que o composer-deploy-dags instala nos
plugins com a versão travada no poetry.lock. O feature-worker e a migração 033 importam
daqui via features.py: é um cálculo só. Sem textstat (o Composer não tem).
"""

import re
from functools import lru_cache

import pyphen

# --- Flesch pt-BR (Martins et al., 1996) ---
# O content vem em markdown do scraper: imagens somem, links ficam só com o texto e URLs
# soltas somem (sem levar a pontuação final, que marca fim de frase).
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+?(?=[.,;:!?)\]]*(?:\s|$))")
# Títulos e itens de lista costumam vir sem ponto: viram blocos próprios (linha em branco).
_MD_HEADING_LINE = re.compile(r"^[ \t]*#{1,6}[ \t].*$", re.MULTILINE)
_MD_LIST_ITEM = re.compile(r"^(?=[ \t]*(?:[-*+]|\d+[.)])[ \t])", re.MULTILINE)
# Palavra: letras (acentuadas incluídas), sem números; composto com hífen é uma palavra.
_PTBR_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
# Fim de frase: [.!?…] (mais aspas/parênteses de fechamento) seguido de espaço ou fim do
# texto (o ponto de "1.500" não quebra), ou linha em branco.
_PTBR_SENTENCE_BREAK = re.compile(r"[.!?…]+[\"'”’»)\]]*(?=\s|$)|\n[ \t]*\n")
_PYPHEN_PTBR = pyphen.Pyphen(lang="pt_BR", left=1, right=1)


@lru_cache(maxsize=65536)
def _syllables_ptbr_word(word: str) -> int:
    """Sílabas de uma palavra minúscula sem hífen: pontos de hifenização + 1."""
    return len(_PYPHEN_PTBR.positions(word)) + 1


def count_syllables_ptbr(word: str) -> int:
    """Sílabas pelo pyphen pt_BR (left=1, right=1); composto com hífen soma as partes.

    Aproximação da divisão silábica: o dicionário de hifenização não separa alguns
    hiatos (saúde → 2, baú → 1) e com left=1 separa encontros iniciais (pneu → 2).
    """
    return sum(_syllables_ptbr_word(part.lower()) for part in word.split("-") if part)


def readability_counts_ptbr(content: str) -> tuple[int, int, int]:
    """(palavras, frases, sílabas) do content para o Flesch pt-BR.

    Frases sem palavra (só números/pontuação) não contam. Abreviações com ponto
    ("Art. 5º", "Sr.") contam como fim de frase.
    """
    text = _MD_IMAGE.sub(" ", content)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _MD_HEADING_LINE.sub(lambda m: f"\n{m.group(0)}\n", text)
    text = _MD_LIST_ITEM.sub("\n", text)
    words = _PTBR_WORD.findall(text)
    sentences = sum(1 for seg in _PTBR_SENTENCE_BREAK.split(text) if _PTBR_WORD.search(seg))
    syllables = sum(count_syllables_ptbr(w) for w in words)
    return len(words), sentences, syllables


def compute_readability_flesch_ptbr(content: str | None) -> float | None:
    """Flesch reading ease adaptado ao português (Martins et al., 1996).

    ``248,835 − 1,015·ASL − 84,6·ASW`` (ASL = palavras/frases, ASW = sílabas/palavras),
    com as contagens de ``readability_counts_ptbr``. Valor cru, sem clamp: pode ficar
    negativo ou passar de 100. Faixas: 75–100 muito fácil, 50–75 fácil, 25–50 difícil,
    0–25 muito difícil. None abaixo de 10 palavras.
    """
    if not content:
        return None
    words, sentences, syllables = readability_counts_ptbr(content)
    if words < 10:
        return None
    return round(248.835 - 1.015 * words / sentences - 84.6 * syllables / words, 2)
