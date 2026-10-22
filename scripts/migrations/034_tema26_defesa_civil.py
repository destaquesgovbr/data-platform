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
     os ids de 19.03*/19.04* deixam de existir) e UNIQUE (campaign, unique_id): uma
     linha por artigo em cada campanha. Contrato de 22/10 com o DS-1 (data-science#49),
     cujo preflight exige esse UNIQUE:
       - `tema26-034`, source `migration-034` (esta migração; `note` = regra aplicada);
       - `tema26-llm-d1`, source `llm:<model_id>` (reclassificação por LLM da D1);
       - `tema26-rollback`, source `migration-034-rollback` (o rollback abaixo).
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
novos) e lê as linhas ainda não revertidas de TODAS as campanhas `tema26-*` menos a do
próprio rollback (a 034, a do LLM da D1 e eventuais reexecuções dela), na ordem
(changed_at, id). Cada artigo auditado volta ao estado anterior à PRIMEIRA mudança,
somando as campanhas, se o estado atual for o da ÚLTIMA (ou ainda apontar para o 26;
senão mantém e conta). Assim, um artigo que o LLM tirou de 05.02.01 e pôs no 26 volta a
05.02.01. Só o que está no 26 sem nenhuma linha de auditoria (ex.: classificado pelo
worker depois do DS-1) é desfeito pelo mapa inverso (26.01* → 19.03*, 26.02* → 19.04*,
26 → 19). Tudo fica registrado na campanha `tema26-rollback`; as linhas lidas ganham
reverted_at e os 26* são apagados. A tabela de auditoria fica (histórico).

Reaplicar depois do rollback: o UPSERT da auditoria (ON CONFLICT (campaign, unique_id))
reaproveita a linha do artigo na campanha, com os códigos novos e reverted_at = NULL. A
campanha do LLM não é reaproveitada: o DS-1 pula artigo já auditado nela, então uma
nova D1 depois de um rollback usa outra campanha `tema26-*` (ex.: `tema26-llm-d1b`).

Depois do apply: sync do Typesense (incremental desde 2025-09-01), BigQuery 002 e
`data-platform bq-merge-theme-changes`. Runbook completo no PR do DP-2.
"""

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass

from loguru import logger
from psycopg2.extras import execute_values

# Contrato da auditoria (plano, 22/10): campanhas separadas por origem.
CAMPAIGN = "tema26-034"
SOURCE = "migration-034"
# Reclassificação por LLM da D1 (DS-1, data-science#49), source "llm:<model_id>".
LLM_CAMPAIGN = "tema26-llm-d1"
ROLLBACK_CAMPAIGN = "tema26-rollback"
ROLLBACK_SOURCE = "migration-034-rollback"
# Toda campanha do tema 26: o rollback (menos a própria) e o MERGE do BigQuery leem assim.
CAMPAIGN_PATTERN = "tema26-%"

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


def audit_endpoints(rows) -> tuple[dict[str, ThemeCodes], dict[str, ThemeCodes]]:
    """Estado antes da PRIMEIRA e depois da ÚLTIMA mudança auditada de cada artigo.

    `rows`: (unique_id, campaign, changed_at, id, antigo, novo) de qualquer campanha do
    tema 26; a ordem é (changed_at, id), não a da lista. Junta a 034 e o LLM da D1: um
    artigo remapeado pela 034 e depois reclassificado pelo LLM tem como ponta antiga o
    estado de antes da 034 e como ponta nova o que o LLM gravou.
    """
    first_old: dict[str, ThemeCodes] = {}
    last_new: dict[str, ThemeCodes] = {}
    for uid, _campaign, _changed_at, _id, old, new in sorted(rows, key=lambda r: (r[2], r[3])):
        first_old.setdefault(uid, old)
        last_new[uid] = new
    return first_old, last_new


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


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

LOCK_THEMES_SQL = """
    SET LOCAL lock_timeout = '10s';
    LOCK TABLE themes IN EXCLUSIVE MODE;
"""

CREATE_AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS news_theme_changes (
    id                      BIGSERIAL PRIMARY KEY,
    campaign                VARCHAR(50)  NOT NULL,
    unique_id               VARCHAR(120) NOT NULL,
    old_l1_code             VARCHAR(20),
    old_l2_code             VARCHAR(20),
    old_l3_code             VARCHAR(20),
    old_most_specific_code  VARCHAR(20),
    new_l1_code             VARCHAR(20),
    new_l2_code             VARCHAR(20),
    new_l3_code             VARCHAR(20),
    new_most_specific_code  VARCHAR(20),
    source                  VARCHAR(50)  NOT NULL,
    note                    TEXT,
    changed_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reverted_at             TIMESTAMPTZ
);
-- Contrato com o DS-1: uma linha por artigo em cada campanha (o preflight dele exige
-- índice único sem predicado exatamente em (campaign, unique_id)). Índice e não
-- constraint inline: vale também se a tabela já existir.
CREATE UNIQUE INDEX IF NOT EXISTS uq_news_theme_changes_campaign_uid
    ON news_theme_changes (campaign, unique_id);
CREATE INDEX IF NOT EXISTS idx_news_theme_changes_changed_at
    ON news_theme_changes (changed_at);
COMMENT ON TABLE news_theme_changes IS
    'Auditoria de mudanças de tema em news (códigos, não ids), uma linha por artigo e '
    'campanha. tema26-034: migração 034 (source migration-034); tema26-llm-d1: '
    'reclassificação por LLM da D1 (source llm:<model_id>); tema26-rollback: rollback '
    'da 034, que preenche reverted_at nas linhas que desfaz.';
"""

UPSERT_THEME_SQL = """
    INSERT INTO themes (code, label, full_name, level, parent_code)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (code) DO UPDATE SET
        label = EXCLUDED.label,
        full_name = EXCLUDED.full_name,
        level = EXCLUDED.level,
        parent_code = EXCLUDED.parent_code
    RETURNING (xmax = 0) AS inserted
"""

THEME_IDS_SQL = "SELECT code, id FROM themes"

LEGACY_PREFIX_SQL = r"SELECT code FROM themes WHERE code ~ '^19\.0[34](\.|$)'"

_NEWS_CODES_SELECT = """
    SELECT n.unique_id, t1.code, t2.code, t3.code, tm.code
    FROM news n
    LEFT JOIN themes t1 ON t1.id = n.theme_l1_id
    LEFT JOIN themes t2 ON t2.id = n.theme_l2_id
    LEFT JOIN themes t3 ON t3.id = n.theme_l3_id
    LEFT JOIN themes tm ON tm.id = n.most_specific_theme_id
"""

_REFERENCES_IDS = """
    n.theme_l1_id = ANY(%(ids)s) OR n.theme_l2_id = ANY(%(ids)s)
    OR n.theme_l3_id = ANY(%(ids)s) OR n.most_specific_theme_id = ANY(%(ids)s)
"""

SELECT_TOUCHED_SQL = (
    _NEWS_CODES_SELECT + "WHERE " + _REFERENCES_IDS + "ORDER BY n.unique_id FOR UPDATE OF n"
)

SELECT_ROLLBACK_SCOPE_SQL = (
    _NEWS_CODES_SELECT
    + "WHERE n.unique_id = ANY(%(uids)s) OR "
    + _REFERENCES_IDS
    + "ORDER BY n.unique_id FOR UPDATE OF n"
)

COUNT_REFERENCES_SQL = "SELECT COUNT(*) FROM news n WHERE " + _REFERENCES_IDS

# Reaplicar depois de um rollback reaproveita a linha (UNIQUE (campaign, unique_id)).
INSERT_AUDIT_SQL = """
    INSERT INTO news_theme_changes (
        campaign, unique_id,
        old_l1_code, old_l2_code, old_l3_code, old_most_specific_code,
        new_l1_code, new_l2_code, new_l3_code, new_most_specific_code,
        source, note
    ) VALUES %s
    ON CONFLICT (campaign, unique_id) DO UPDATE SET
        old_l1_code = EXCLUDED.old_l1_code,
        old_l2_code = EXCLUDED.old_l2_code,
        old_l3_code = EXCLUDED.old_l3_code,
        old_most_specific_code = EXCLUDED.old_most_specific_code,
        new_l1_code = EXCLUDED.new_l1_code,
        new_l2_code = EXCLUDED.new_l2_code,
        new_l3_code = EXCLUDED.new_l3_code,
        new_most_specific_code = EXCLUDED.new_most_specific_code,
        source = EXCLUDED.source,
        note = EXCLUDED.note,
        changed_at = EXCLUDED.changed_at,
        reverted_at = NULL
"""

UPDATE_NEWS_SQL = """
    UPDATE news AS n SET
        theme_l1_id = v.l1,
        theme_l2_id = v.l2,
        theme_l3_id = v.l3,
        most_specific_theme_id = v.ms
    FROM (VALUES %s) AS v (unique_id, l1, l2, l3, ms)
    WHERE n.unique_id = v.unique_id
"""
UPDATE_NEWS_TEMPLATE = "(%s, %s::int, %s::int, %s::int, %s::int)"

DELETE_THEMES_SQL = "DELETE FROM themes WHERE code = ANY(%s)"

# Hierarquias incoerentes que sobram em 19/26 depois do remap (fora do escopo da 034).
INCONSISTENT_19_26_SQL = """
    SELECT COUNT(*) FROM news n
    JOIN themes t1 ON t1.id = n.theme_l1_id
    LEFT JOIN themes t2 ON t2.id = n.theme_l2_id
    LEFT JOIN themes t3 ON t3.id = n.theme_l3_id
    WHERE t1.code IN ('19', '26')
      AND ((t2.id IS NOT NULL AND t2.parent_code IS DISTINCT FROM t1.code)
           OR (t3.id IS NOT NULL AND t3.parent_code IS DISTINCT FROM t2.code))
"""

# Linhas que o rollback desfaz: todas as campanhas tema26-* menos a dele, ainda ativas.
_ROLLBACK_SCOPE = """
    campaign LIKE %(pattern)s AND campaign <> %(rollback)s AND reverted_at IS NULL
"""
ROLLBACK_SCOPE_PARAMS = {"pattern": CAMPAIGN_PATTERN, "rollback": ROLLBACK_CAMPAIGN}

AUDIT_ROWS_SQL = (
    """
    SELECT unique_id, campaign, changed_at, id,
        old_l1_code, old_l2_code, old_l3_code, old_most_specific_code,
        new_l1_code, new_l2_code, new_l3_code, new_most_specific_code
    FROM news_theme_changes
    WHERE"""
    + _ROLLBACK_SCOPE
    + "ORDER BY changed_at, id"
)

MARK_REVERTED_SQL = (
    "UPDATE news_theme_changes SET reverted_at = NOW() WHERE"
    + _ROLLBACK_SCOPE
    + "RETURNING campaign"
)

DRY_RUN_SAVEPOINT = "tema26_034_dry_run"


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def _upsert_themes(cursor, themes) -> tuple[int, int]:
    inserted = updated = 0
    for code, label, level, parent in themes:
        cursor.execute(UPSERT_THEME_SQL, (code, label, f"{code} {label}", level, parent))
        if cursor.fetchone()[0]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def _theme_ids(cursor) -> dict[str, int]:
    cursor.execute(THEME_IDS_SQL)
    return dict(cursor.fetchall())


def _rows_to_codes(rows) -> dict[str, ThemeCodes]:
    return {row[0]: ThemeCodes(*row[1:]) for row in rows}


def _ids_for(codes: ThemeCodes, ids: dict[str, int]) -> tuple:
    missing = [code for code in codes.values() if code is not None and code not in ids]
    if missing:
        raise ValueError(f"códigos sem linha em themes: {sorted(set(missing))}")
    return tuple(ids[code] if code is not None else None for code in codes.values())


def _write_changes(
    cursor,
    changes: list[tuple[str, ThemeCodes, ThemeCodes, str]],
    ids: dict[str, int],
    campaign: str,
    source: str,
) -> None:
    """Auditoria + UPDATE de news para [(unique_id, antigo, novo, nota)]."""
    if not changes:
        return
    execute_values(
        cursor,
        INSERT_AUDIT_SQL,
        [
            (campaign, uid, *old.values(), *new.values(), source, note)
            for uid, old, new, note in changes
        ],
        page_size=1000,
    )
    execute_values(
        cursor,
        UPDATE_NEWS_SQL,
        [(uid, *_ids_for(new, ids)) for uid, _old, new, _note in changes],
        template=UPDATE_NEWS_TEMPLATE,
        page_size=1000,
    )


def _delete_by_level(cursor, themes, levels) -> int:
    deleted = 0
    for level in levels:
        codes = [code for code, _label, lvl, _parent in themes if lvl == level]
        cursor.execute(DELETE_THEMES_SQL, (codes,))
        deleted += cursor.rowcount
    return deleted


def _count_references(cursor, ids: list[int]) -> int:
    if not ids:
        return 0
    cursor.execute(COUNT_REFERENCES_SQL, {"ids": ids})
    return cursor.fetchone()[0]


def _apply(cursor) -> dict:
    cursor.execute(LOCK_THEMES_SQL)
    cursor.execute(CREATE_AUDIT_SQL)

    cursor.execute(LEGACY_PREFIX_SQL)
    unexpected = sorted({code for (code,) in cursor.fetchall()} - LEGACY_CODES)
    if unexpected:
        raise ValueError(f"códigos em 19.03/19.04 fora do contrato do tema 26: {unexpected}")

    inserted, updated = _upsert_themes(cursor, THEMES_26)
    ids = _theme_ids(cursor)
    legacy_ids = [ids[code] for code in sorted(LEGACY_CODES) if code in ids]

    touched: dict[str, ThemeCodes] = {}
    if legacy_ids:
        cursor.execute(SELECT_TOUCHED_SQL, {"ids": legacy_ids})
        touched = _rows_to_codes(cursor.fetchall())

    changes = []
    rules: Counter = Counter()
    refs_before: Counter = Counter()
    for uid, old in touched.items():
        new, rule = remap(old)
        changes.append((uid, old, new, rule))
        rules[rule] += 1
        for code in set(old.values()) & LEGACY_CODES:
            refs_before[code] += 1

    _write_changes(cursor, changes, ids, CAMPAIGN, SOURCE)

    remaining = _count_references(cursor, legacy_ids)
    if remaining:
        raise RuntimeError(f"{remaining} artigos ainda apontam para 19.03/19.04 depois do remap")
    deleted = _delete_by_level(cursor, LEGACY_THEMES, levels=(3, 2))

    cursor.execute(INCONSISTENT_19_26_SQL)
    inconsistent = cursor.fetchone()[0]

    return {
        "campaign": CAMPAIGN,
        "themes_inserted": inserted,
        "themes_updated": updated,
        "articles": len(changes),
        "by_rule": dict(rules.most_common()),
        "legacy_refs_before": dict(sorted(refs_before.items())),
        "transitions": transition_counts([(old, new) for _uid, old, new, _r in changes]),
        "by_new_most_specific": dict(
            Counter(new.most_specific for _uid, _old, new, _r in changes).most_common()
        ),
        "legacy_themes_deleted": deleted,
        "inconsistent_l1_19_26_after": inconsistent,
    }


def _revert(cursor) -> dict:
    cursor.execute(LOCK_THEMES_SQL)
    cursor.execute(CREATE_AUDIT_SQL)

    ids = _theme_ids(cursor)
    legacy_inserted = 0
    if "19" in ids:
        legacy_inserted, _ = _upsert_themes(cursor, LEGACY_THEMES)
        ids = _theme_ids(cursor)
    ids_26 = [ids[code] for code in sorted(CODES_26) if code in ids]

    cursor.execute(AUDIT_ROWS_SQL, ROLLBACK_SCOPE_PARAMS)
    audit_rows = [
        (uid, campaign, changed_at, row_id, ThemeCodes(*codes[:4]), ThemeCodes(*codes[4:]))
        for uid, campaign, changed_at, row_id, *codes in cursor.fetchall()
    ]
    first_old, last_new = audit_endpoints(audit_rows)
    audited_by_campaign = Counter(campaign for _uid, campaign, *_rest in audit_rows)

    current: dict[str, ThemeCodes] = {}
    if first_old or ids_26:
        cursor.execute(SELECT_ROLLBACK_SCOPE_SQL, {"uids": sorted(first_old), "ids": ids_26})
        current = _rows_to_codes(cursor.fetchall())

    changes = []
    reasons: Counter = Counter()
    for uid, now in current.items():
        if uid in first_old:
            target, reason = rollback_target(now, first_old[uid], last_new[uid])
        else:
            target, reason = inverse(now), "mapa_inverso"
        reasons[reason] += 1
        if target is not None and target != now:
            changes.append((uid, now, target, reason))

    _write_changes(cursor, changes, ids, ROLLBACK_CAMPAIGN, ROLLBACK_SOURCE)
    cursor.execute(MARK_REVERTED_SQL, ROLLBACK_SCOPE_PARAMS)
    marked = Counter(campaign for (campaign,) in cursor.fetchall())

    remaining = _count_references(cursor, ids_26)
    if remaining:
        raise RuntimeError(f"{remaining} artigos ainda apontam para o 26 depois do rollback")
    deleted = _delete_by_level(cursor, THEMES_26, levels=(3, 2, 1))

    return {
        "campaign_pattern": CAMPAIGN_PATTERN,
        "audited_rows_by_campaign": dict(sorted(audited_by_campaign.items())),
        "audited_articles": len(first_old),
        "legacy_themes_restored": legacy_inserted,
        "articles": len(changes),
        "by_reason": dict(reasons.most_common()),
        "transitions": transition_counts([(old, new) for _uid, old, new, _r in changes]),
        "campaign_rows_reverted": dict(sorted(marked.items())),
        "themes_26_deleted": deleted,
    }


def _run(conn, action, dry_run: bool, label: str) -> dict:
    """Executa `action` na transação do runner; no dry-run, num SAVEPOINT desfeito."""
    cursor = conn.cursor()
    try:
        if dry_run:
            cursor.execute(f"SAVEPOINT {DRY_RUN_SAVEPOINT}")
        stats = action(cursor)
        stats["dry_run"] = dry_run
        if dry_run:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {DRY_RUN_SAVEPOINT}")
            cursor.execute(f"RELEASE SAVEPOINT {DRY_RUN_SAVEPOINT}")
        # O runner descarta o histórico do dry-run (rollback): o log é onde as contagens ficam.
        logger.info(
            f"034 {label}{' dry-run' if dry_run else ''}: " + json.dumps(stats, ensure_ascii=False)
        )
        return stats
    finally:
        cursor.close()


def describe() -> str:
    return "Tema 26 Defesa Civil e Gestão de Desastres: remap de 19.03/19.04 com auditoria"


def migrate(conn, dry_run: bool = False) -> dict:
    return _run(conn, _apply, dry_run, "migrate")


def rollback(conn, dry_run: bool = False) -> dict:
    return _run(conn, _revert, dry_run, "rollback")


if __name__ == "__main__":
    import argparse

    import psycopg2

    parser = argparse.ArgumentParser(description=describe())
    parser.add_argument("--dry-run", action="store_true", help="Executa e desfaz; só contagens")
    parser.add_argument("--confirm", action="store_true", help="Aplica (commit)")
    parser.add_argument("--rollback", action="store_true", help="Desfaz pela auditoria")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("Must specify --dry-run or --confirm")
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    try:
        fn = rollback if args.rollback else migrate
        result = fn(conn, dry_run=args.dry_run)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        conn.close()
