"""
Tema 26 "Defesa Civil e Gestão de Desastres": novos códigos, remap determinístico e
auditoria (DP-2, D0).

Contrato (TH-1, test-data/themes_tree_enriched_full.yaml v3.2):
  - L1 '26' Defesa Civil e Gestão de Desastres;
  - L2 '26.01' Defesa Civil, com 26.01.01–05 = os L3 de 19.03.01–05 (mesmos rótulos);
  - L2 '26.02' Situações de Emergência, com 26.02.01–05 = os L3 de 19.04.01–05;
  - 19.03* e 19.04* saem de `themes`.

Numa transação só (o runner faz o commit; dry-run = mesma execução num SAVEPOINT
desfeito, com as contagens no log):
  1. LOCK em `themes` (EXCLUSIVE, lock_timeout 10s): leituras seguem, mas nenhuma
     escrita em `news` que aponte para um tema (a FK pega FOR KEY SHARE em `themes`)
     entra até o commit. O worker ao vivo espera alguns segundos.
  2. Tabela de auditoria `news_theme_changes` (IF NOT EXISTS), com códigos (não ids:
     os ids de 19.03*/19.04* deixam de existir). A reclassificação por LLM da D1
     (data-science, DS-1) grava na mesma tabela, com a mesma campanha e outra origem.
  3. Upsert de 26/26.01/26.02/26.0x.0y em `themes` (ON CONFLICT (code)), pai antes do
     filho. Nunca usar scripts/populate_themes.py em produção (DELETE + ids novos).
  4. Remap de news.theme_l1/l2/l3/most_specific de todo artigo que referencia
     19.03*/19.04* em qualquer coluna (ver `remap`); uma linha de auditoria por artigo.
  5. DELETE de 19.03*/19.04* (L3 antes de L2: `parent_code` tem ON DELETE SET NULL).
     As FKs de `news` são a rede de segurança: sobrou referência, a transação aborta.

Regra do remap (`remap`), por código, com a hierarquia reconstruída a partir de uma
âncora (o código mais específico confiável):
  - âncora = L3, a menos que o L3 e o L2 apontem para L1 diferentes depois do remap E o
    par L1–L2 seja coerente (pai do L2 = L1): aí o par decide e o L3 sai;
  - sem L3: âncora = L2; sem L2/L3: o most_specific (se legado) ou o L1;
  - L1/L2/L3/most_specific novos = cadeia da âncora remapeada (most_specific = âncora).
As 4 hierarquias incoerentes com o 19 (contagens de base de 21/10, seção C.4):
  - (15, 19.04, 19.04.04) → (26, 26.02, 26.02.04): L2–L3 coerentes, o L1 é corrigido;
  - (19, 19.03, 19.04.01) → (26, 26.02, 26.02.01): ambos no 26, o L3 decide;
  - (19, 19.02, 19.03.01) → (19, 19.02, —): visita da ESD ao Chile, tema militar; o
    par L1–L2 decide, o L3 sai e o artigo segue no 19 (reclassificação da D1);
  - (19, 20.02, 20.02.03): nenhum código legado, fica fora da 034 (D1). Contado em
    `untouched_inconsistent_l1_19`.

Rollback (a partir da auditoria, também numa transação): recria 19.03*/19.04* (ids
novos), devolve cada artigo da campanha ao estado anterior à PRIMEIRA mudança dela se o
estado atual for o da ÚLTIMA (ou ainda apontar para o 26; senão mantém e conta),
desfaz por mapa inverso (26.01* → 19.03*, 26.02* → 19.04*, 26 → 19) o que estiver no
26 fora da auditoria (ex.: classificado pelo worker depois do DS-1), registra tudo na
campanha `tema26-rollback`, marca a campanha como revertida (reverted_at) e apaga os
26*. A tabela de auditoria fica (histórico).

Depois do apply: sync do Typesense (incremental desde 2025-09-01), BigQuery 002 e
`data-platform bq-merge-theme-changes`. Runbook completo no PR do DP-2.
"""

from collections import Counter
from dataclasses import dataclass

CAMPAIGN = "tema26"
SOURCE = "034_remap"
ROLLBACK_CAMPAIGN = "tema26-rollback"
ROLLBACK_SOURCE = "034_rollback"

# (code, label, level, parent_code), pai antes do filho.
THEMES_26: tuple[tuple[str, str, int, str | None], ...] = (
    ("26", "Defesa Civil e Gestão de Desastres", 1, None),
    ("26.01", "Defesa Civil", 2, "26"),
    ("26.01.01", "Preparação para Desastres", 3, "26.01"),
    ("26.01.02", "Planejamento de Evacuação", 3, "26.01"),
    ("26.01.03", "Resposta a Desastres", 3, "26.01"),
    ("26.01.04", "Monitoramento de Riscos Naturais", 3, "26.01"),
    ("26.01.05", "Gestão de Abrigos", 3, "26.01"),
    ("26.02", "Situações de Emergência", 2, "26"),
    ("26.02.01", "Resgate e Salvamento", 3, "26.02"),
    ("26.02.02", "Logística de Emergência", 3, "26.02"),
    ("26.02.03", "Ações Humanitárias", 3, "26.02"),
    ("26.02.04", "Reconstrução Pós-Desastre", 3, "26.02"),
    ("26.02.05", "Assistência a Deslocados Internos", 3, "26.02"),
)

# O que sai (rótulos de produção em 21/10/2026), para o rollback recriar.
LEGACY_THEMES: tuple[tuple[str, str, int, str], ...] = (
    ("19.03", "Defesa Civil", 2, "19"),
    ("19.03.01", "Preparação para Desastres", 3, "19.03"),
    ("19.03.02", "Planejamento de Evacuação", 3, "19.03"),
    ("19.03.03", "Resposta a Desastres", 3, "19.03"),
    ("19.03.04", "Monitoramento de Riscos Naturais", 3, "19.03"),
    ("19.03.05", "Gestão de Abrigos", 3, "19.03"),
    ("19.04", "Situações de Emergência", 2, "19"),
    ("19.04.01", "Resgate e Salvamento", 3, "19.04"),
    ("19.04.02", "Logística de Emergência", 3, "19.04"),
    ("19.04.03", "Ações Humanitárias", 3, "19.04"),
    ("19.04.04", "Reconstrução Pós-Desastre", 3, "19.04"),
    ("19.04.05", "Assistência a Deslocados Internos", 3, "19.04"),
)

_PREFIX_MAP = {"19.03": "26.01", "19.04": "26.02"}
CODE_MAP: dict[str, str] = {
    code: _PREFIX_MAP[code[:5]] + code[5:] for code, _label, _level, _parent in LEGACY_THEMES
}
INVERSE_MAP: dict[str, str] = {new: old for old, new in CODE_MAP.items()} | {"26": "19"}

LEGACY_CODES = frozenset(CODE_MAP)
CODES_26 = frozenset(code for code, _label, _level, _parent in THEMES_26)

COLUMNS = ("theme_l1", "theme_l2", "theme_l3", "most_specific")


# ---------------------------------------------------------------------------
# Regras puras
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeCodes:
    """Códigos de tema de um artigo: theme_l1/l2/l3 e most_specific."""

    l1: str | None
    l2: str | None
    l3: str | None
    most_specific: str | None

    def values(self) -> tuple[str | None, str | None, str | None, str | None]:
        return (self.l1, self.l2, self.l3, self.most_specific)


def map_code(code: str | None) -> str | None:
    return CODE_MAP.get(code, code) if code is not None else None


def _parent(code: str) -> str | None:
    return code.rsplit(".", 1)[0] if "." in code else None


def _top(code: str) -> str:
    return code.split(".", 1)[0]


def chain(code: str) -> ThemeCodes:
    """Hierarquia completa de um código (os códigos da taxonomia são NN, NN.NN, NN.NN.NN)."""
    parts = code.split(".")
    l1 = parts[0]
    l2 = ".".join(parts[:2]) if len(parts) >= 2 else None
    l3 = code if len(parts) >= 3 else None
    return ThemeCodes(l1, l2, l3, code)


def touches_legacy(codes: ThemeCodes) -> bool:
    return any(code in LEGACY_CODES for code in codes.values())


def references_26(codes: ThemeCodes) -> bool:
    return any(code is not None and _top(code) == "26" for code in codes.values())


def _is_coherent(codes: ThemeCodes) -> bool:
    deepest = codes.l3 or codes.l2 or codes.l1
    return deepest is not None and codes == chain(deepest)


def remap(old: ThemeCodes) -> tuple[ThemeCodes, str]:
    """Novos códigos de um artigo e a regra aplicada (ver docstring do módulo).

    Regras: "remap" (hierarquia coerente, só renumera), "hierarquia_reconstruida"
    (incoerente; cadeia refeita a partir da âncora), "l3_descartado" (o par L1–L2
    decidiu e o L3 saiu) e "sem_codigo_legado" (nada a fazer).
    """
    if not touches_legacy(old):
        return old, "sem_codigo_legado"

    l2n, l3n = map_code(old.l2), map_code(old.l3)
    l1_l2_coherent = old.l2 is not None and _parent(old.l2) == old.l1
    dropped_l3 = False
    if l3n is not None and (l2n is None or _top(l3n) == _top(l2n) or not l1_l2_coherent):
        anchor = l3n
    elif l2n is not None:
        anchor = l2n
        dropped_l3 = old.l3 is not None
    elif old.most_specific in LEGACY_CODES:
        anchor = map_code(old.most_specific)
    else:
        anchor = map_code(old.l1)

    new = chain(anchor)
    if dropped_l3:
        rule = "l3_descartado"
    elif _is_coherent(old):
        rule = "remap"
    else:
        rule = "hierarquia_reconstruida"
    return new, rule


def rollback_target(
    current: ThemeCodes, first_old: ThemeCodes, last_new: ThemeCodes
) -> tuple[ThemeCodes | None, str]:
    """Para onde um artigo da campanha volta no rollback (None = fica como está)."""
    if current == last_new:
        return first_old, "revertido"
    if references_26(current):
        return first_old, "revertido_forcado"
    return None, "mantido"


def inverse(codes: ThemeCodes) -> ThemeCodes:
    """Desfaz o 26 por código, coluna a coluna (artigos no 26 fora da auditoria)."""
    return ThemeCodes(
        *(INVERSE_MAP.get(code, code) if code is not None else None for code in codes.values())
    )


def transition_counts(pairs: list[tuple[ThemeCodes, ThemeCodes]]) -> dict[str, dict[str, int]]:
    """Contagem "antigo→novo" por coluna, só do que muda (∅ = NULL)."""
    counts: dict[str, Counter] = {column: Counter() for column in COLUMNS}
    for old, new in pairs:
        for column, before, after in zip(COLUMNS, old.values(), new.values(), strict=True):
            if before != after:
                counts[column][f"{before or '∅'}→{after or '∅'}"] += 1
    return {column: dict(counter.most_common()) for column, counter in counts.items()}
