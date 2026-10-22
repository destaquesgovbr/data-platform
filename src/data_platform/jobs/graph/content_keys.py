"""Chave de quase-duplicata de conteudo (news.content_key) — regra H5 do DP-1b.

O content_hash (migracoes 009/010) so junta textos identicos, e o conteudo guardado embute as URLs
de imagem e de link de cada orgao: o hash pega 0,4% das republicacoes entre orgaos. Este modulo
agrupa quase-duplicatas e grava em news.content_key o unique_id do LIDER do grupo (o artigo mais
antigo). Artigo sem quase-duplicata fica com NULL e os leitores caem no hash exato via
COALESCE(n.content_key, n.content_hash, n.unique_id) (ARTICLE_CONTENT_KEY_SQL em edges.py e
_CONTENT_DEDUP_KEY_SQL na graphql-api); os espacos de chave nao colidem (unique_id x 16 hex).

Regra H5 (relatorio ~/dgb-runs/dedup_near_dup_report_2026-10-21.md, §6; calibrada em 3,4 mil
artigos: recall 92% e precisao 99% entre orgaos):

- Normalizacao: clean_markdown (tira imagens, troca link pelo texto, tira URLs) + normalize_text
  (a mesma da migracao 010); shingles = hashes de 64 bits dos 5-gramas de palavras. Conteudo
  utilizavel: >= 30 palavras e sem tela de login nas 20 primeiras.
- E1 (conteudo): os dois utilizaveis e (dt <= 3 dias com J >= 0,5, ou C >= 0,8 com o lado menor
  >= 50 shingles) ou (dt <= 7 dias com J >= 0,8). J = Jaccard; C = contencao (comum / menor).
- E2 (titulo): titulos normalizados iguais, >= 4 tokens, fora da lista de exclusao, dt <= 2 dias
  e (algum conteudo inutilizavel, ou J >= 0,1, ou C >= 0,3).
- Guardas, quando os titulos diferem ou quando o titulo e o mesmo no mesmo orgao (com os dois
  conteudos utilizaveis; vale para E1 e E2):
  - G1, familia de modelo: membro = >= 2 irmaos do mesmo orgao com J >= 0,6, dt <= 1 dia e titulo
    diferente, ou o mesmo titulo com J < 0,95 (Enem/Censo por UF; CIN por UF com o titulo do
    modelo). Descarta o par se os dois sao membros, ou se um e e J < 0,95. Variantes por UF de
    um mesmo modelo sao conteudos DISTINTOS (decisao de produto, 21/10).
  - G2, mesmo orgao: exige J >= 0,8, dt <= 1 dia e titulos que nao sejam troca de "slot"
    (notas recorrentes: "NIS de final 5/6", "Pe-de-Meia: nascidos em ..."). Com o mesmo
    titulo e J >= 0,95 (o mesmo texto: recaptura ou repostagem do proprio orgao) basta a E1,
    ate 7 dias.
  - O relatorio (§6.3) aplicava as guardas so com titulos diferentes; o mesmo titulo no mesmo
    orgao juntava variantes por UF e comunicados recorrentes (revisao do PR, 22/10). O mesmo
    titulo entre orgaos diferentes segue sem guarda.
- Agrupamento por lider (estrela, nao componente conexo): em ordem de (published_at, unique_id),
  cada artigo entra no grupo do lider com quem tem aresta direta (o de maior J); sem aresta com
  nenhum lider, vira lider.

Execucao em lote (compute_content_keys), nunca na ingestao: stream ordenado por published_at
(cursor no servidor), indice invertido de shingles numa janela deslizante de 7 dias, J e C exatos
dos candidatos (>= 3 shingles em comum), regras e guardas, lider, e UPDATE em lote so das linhas
cuja chave mudou. A DAG project_entity_graph recalcula os ultimos RECOMPUTE_DAYS dias a cada run
(absorve republicacoes tardias); os CONTEXT_DAYS dias anteriores entram como contexto, semeados
pela chave ja gravada. Backfill do corpus inteiro: migracao 036.

So stdlib + psycopg2: o Composer recebe jobs/graph como plugin (composer-deploy-dags.yaml).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limiares (constantes de codigo: revalidar depois do backfill, relatorio §7.6)
# ---------------------------------------------------------------------------

DAY_SECONDS = 86400.0

SHINGLE_SIZE = 5
MIN_USABLE_WORDS = 30
LOGIN_WALL_MARKER = "necessario autenticar para visualizar"
LOGIN_WALL_HEAD_WORDS = 20

# Candidatos: >= N shingles em comum, achados por indice invertido. Cada shingle guarda no maximo
# POSTINGS_CAP artigos da janela — os MAIS ANTIGOS, porque o lider e sempre o mais antigo do
# grupo: boilerplate de orgao nao vira O(n^2) e uma copia tardia de um grupo grande ainda acha o
# lider.
CANDIDATE_MIN_SHARED_SHINGLES = 3
POSTINGS_CAP = 50
TITLE_POSTINGS_CAP = 50
MAX_PAIR_DAYS = 7

# E1 (conteudo)
E1_NEAR_MAX_DAYS = 3
E1_NEAR_MIN_JACCARD = 0.5
E1_MIN_CONTAINMENT = 0.8
E1_CONTAINMENT_MIN_SHINGLES = 50
E1_FAR_MAX_DAYS = 7
E1_FAR_MIN_JACCARD = 0.8

# E2 (titulo)
E2_MIN_TITLE_TOKENS = 4
E2_MAX_DAYS = 2
E2_MIN_JACCARD = 0.1
E2_MIN_CONTAINMENT = 0.3
E2_TITLE_BLOCKLIST = frozenset(
    {
        "nota a imprensa",
        "nota oficial",
        "nota de pesar",
        "participacoes sociais em andamento",
    }
)
E2_TITLE_BLOCK_RE = re.compile(r"acompanhe a agenda|nis de final|recebem parcela")

# G1 (familia de modelo)
G1_SIBLING_MIN_JACCARD = 0.6
G1_SIBLING_MAX_DAYS = 1
G1_MIN_SIBLINGS = 2
G1_MEMBER_MIN_JACCARD = 0.95  # "o mesmo texto": membro ainda junta; mesmo titulo nao e irmao

# G2 (mesmo orgao) e troca de slot no titulo
G2_MIN_JACCARD = 0.8
G2_MAX_DAYS = 1
SLOT_MAX_TOKENS = 5
SLOT_MIN_SHARED_FRACTION = 0.5
ISSUER_RE = re.compile(
    r"\b(governo|ministerio|ministro|ministra|presidente|lula|secretaria|mgi|mec|mds|mps|inss"
    r"|receita|saude|federal|brasil)\b"
)

# Janela de execucao
RECOMPUTE_DAYS = 10
CONTEXT_DAYS = 7
FETCH_SIZE = 1000
UPDATE_BATCH_SIZE = 1000

# ---------------------------------------------------------------------------
# Normalizacao
# ---------------------------------------------------------------------------

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACES_RE = re.compile(r"\s+")


def clean_markdown(text: str | None) -> str:
    """Tira imagens markdown, troca links pelo texto do link e remove URLs soltas."""
    if not text:
        return ""
    text = _IMAGE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    return _URL_RE.sub(" ", text)


def normalize_text(text: str | None) -> str:
    """NFKD -> ASCII, minusculas, sem pontuacao, espacos colapsados (a mesma da migracao 010)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _PUNCT_RE.sub("", text.lower())
    return _SPACES_RE.sub(" ", text).strip()


def content_words(content: str | None) -> list[str]:
    return normalize_text(clean_markdown(content)).split()


def _hash64(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")


def shingle_set(words: list[str]) -> frozenset[int]:
    """Hashes de 64 bits dos 5-gramas de palavras (texto com < 5 palavras vira 1 shingle)."""
    if len(words) < SHINGLE_SIZE:
        return frozenset({_hash64(" ".join(words))}) if words else frozenset()
    return frozenset(
        _hash64(" ".join(words[i : i + SHINGLE_SIZE])) for i in range(len(words) - SHINGLE_SIZE + 1)
    )


def is_usable(words: list[str]) -> bool:
    """Conteudo utilizavel: >= 30 palavras e sem tela de login nas 20 primeiras."""
    if len(words) < MIN_USABLE_WORDS:
        return False
    return LOGIN_WALL_MARKER not in " ".join(words[:LOGIN_WALL_HEAD_WORDS])


def title_eligible(normalized_title: str) -> bool:
    """O titulo normalizado pode ligar artigos pela E2 (>= 4 tokens e fora da lista)?"""
    if len(normalized_title.split()) < E2_MIN_TITLE_TOKENS:
        return False
    if normalized_title in E2_TITLE_BLOCKLIST:
        return False
    return not E2_TITLE_BLOCK_RE.search(normalized_title)


def similarity(a: frozenset[int], b: frozenset[int]) -> tuple[float, float, int]:
    """(Jaccard, contencao, tamanho do menor conjunto) entre dois conjuntos de shingles."""
    if not a or not b:
        return 0.0, 0.0, 0
    inter = len(a & b)
    smaller = min(len(a), len(b))
    return inter / (len(a) + len(b) - inter), inter / smaller, smaller


def slot_variant(title_a: str, title_b: str) -> bool:
    """Titulos (normalizados) que so trocam um "slot": modelo recorrente do mesmo orgao.

    Um unico trecho contiguo de <= 5 tokens difere nos dois lados, prefixo + sufixo em comum
    cobrem >= 50% do titulo mais longo e o trecho nao tem palavra de emissor (secom/planalto
    reescrevem o emissor no titulo de uma republicacao).
    """
    a, b = title_a.split(), title_b.split()
    if a == b:
        return False
    shortest = min(len(a), len(b))
    prefix = 0
    while prefix < shortest and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while suffix < shortest - prefix and a[-1 - suffix] == b[-1 - suffix]:
        suffix += 1
    diff_a, diff_b = a[prefix : len(a) - suffix], b[prefix : len(b) - suffix]
    if not diff_a or not diff_b or len(diff_a) > SLOT_MAX_TOKENS or len(diff_b) > SLOT_MAX_TOKENS:
        return False
    if prefix + suffix < SLOT_MIN_SHARED_FRACTION * max(len(a), len(b)):
        return False
    return not (ISSUER_RE.search(" ".join(diff_a)) or ISSUER_RE.search(" ".join(diff_b)))


# ---------------------------------------------------------------------------
# Plano (puro, sem banco)
# ---------------------------------------------------------------------------


class ArticleRow(NamedTuple):
    """Uma linha do stream, na ordem do SELECT."""

    unique_id: str
    title: str | None
    content: str | None
    agency: str | None
    published_at: datetime
    content_key: str | None = None


_CONTEXT, _TARGET, _LOOKAHEAD = "context", "target", "lookahead"


class _Doc:
    __slots__ = (
        "idx",
        "uid",
        "ts",
        "agency",
        "ntitle",
        "title_ok",
        "usable",
        "shingles",
        "stored_key",
        "role",
    )

    def __init__(self, idx: int, row: ArticleRow, role: str) -> None:
        words = content_words(row.content)
        self.idx = idx
        self.uid = row.unique_id
        self.ts = row.published_at.timestamp()
        self.agency = row.agency
        self.ntitle = normalize_text(row.title)
        self.title_ok = title_eligible(self.ntitle)
        self.usable = is_usable(words)
        # So conteudo utilizavel entra no indice de shingles (E1/G1); a E2 nao precisa de J
        # quando um lado e inutilizavel. Liberado quando o artigo sai da janela.
        self.shingles: frozenset[int] | None = shingle_set(words) if self.usable else None
        self.stored_key = row.content_key
        self.role = role


class _Pair(NamedTuple):
    jaccard: float
    containment: float
    smaller: int
    days: float
    title_edge: bool


@dataclass
class ContentKeyPlan:
    """keys: content_key desejada dos artigos gravaveis (alvo + lideres do contexto com grupo);
    changes: (unique_id, content_key) que diferem do gravado, na ordem do stream."""

    keys: dict[str, str | None] = field(default_factory=dict)
    changes: list[tuple[str, str | None]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def _e1_similar(p: _Pair) -> bool:
    near = p.days <= E1_NEAR_MAX_DAYS and (
        p.jaccard >= E1_NEAR_MIN_JACCARD
        or (p.containment >= E1_MIN_CONTAINMENT and p.smaller >= E1_CONTAINMENT_MIN_SHINGLES)
    )
    far = p.days <= E1_FAR_MAX_DAYS and p.jaccard >= E1_FAR_MIN_JACCARD
    return near or far


def _siblings(a: _Doc, b: _Doc, p: _Pair) -> bool:
    """Irmaos do G1: mesmo orgao, J >= 0,6, dt <= 1 dia e titulo diferente — ou o mesmo titulo
    com J < 0,95 (variante por UF com o titulo do modelo; a recaptura, J ~ 1, nao conta)."""
    return (
        a.agency == b.agency
        and p.jaccard >= G1_SIBLING_MIN_JACCARD
        and p.days <= G1_SIBLING_MAX_DAYS
        and (a.ntitle != b.ntitle or p.jaccard < G1_MEMBER_MIN_JACCARD)
    )


def _is_edge(a: _Doc, b: _Doc, p: _Pair, family: set[int]) -> bool:
    if not (a.usable and b.usable):
        # Sem J confiavel (tela de login, trecho curto), so a E2 decide, sem guardas.
        return p.title_edge
    if not (p.title_edge or _e1_similar(p)):
        return False
    if a.ntitle == b.ntitle and a.agency != b.agency:
        return True  # mesmo titulo entre orgaos: republicacao (mec-Sergipe -> inep-Sergipe)
    # Daqui em diante: titulos diferentes, ou o mesmo titulo no mesmo orgao (variantes por UF
    # com o titulo do modelo e notas recorrentes tambem repetem o titulo).
    a_member, b_member = a.idx in family, b.idx in family
    if a_member and b_member:
        return False
    if (a_member or b_member) and p.jaccard < G1_MEMBER_MIN_JACCARD:
        return False
    if a.agency == b.agency:
        if a.ntitle == b.ntitle and p.jaccard >= G1_MEMBER_MIN_JACCARD:
            return True  # o mesmo texto e o mesmo titulo: recaptura ou repostagem do orgao
        if p.jaccard < G2_MIN_JACCARD or p.days > G2_MAX_DAYS:
            return False
        if slot_variant(a.ntitle, b.ntitle):
            return False
    return True


class _Window:
    """Janela deslizante: indice invertido de shingles (7 dias) e de titulos (2 dias)."""

    def __init__(self, docs: list[_Doc]) -> None:
        self.docs = docs
        self.shingle_window: deque[int] = deque()
        self.title_window: deque[int] = deque()
        self.postings: dict[int, list[int]] = {}
        self.titles: dict[str, list[int]] = {}

    def evict(self, now_ts: float) -> None:
        cutoff = now_ts - MAX_PAIR_DAYS * DAY_SECONDS
        while self.shingle_window and self.docs[self.shingle_window[0]].ts < cutoff:
            old = self.docs[self.shingle_window.popleft()]
            # Postings em ordem cronologica: o artigo que sai e o primeiro de cada lista em que
            # entrou (os mais antigos ja sairam antes dele).
            for s in old.shingles or ():
                plist = self.postings.get(s)
                if plist and plist[0] == old.idx:
                    plist.pop(0)
                    if not plist:
                        del self.postings[s]
            old.shingles = None
        cutoff = now_ts - E2_MAX_DAYS * DAY_SECONDS
        while self.title_window and self.docs[self.title_window[0]].ts < cutoff:
            old = self.docs[self.title_window.popleft()]
            tlist = self.titles.get(old.ntitle)
            if tlist and tlist[0] == old.idx:
                tlist.pop(0)
                if not tlist:
                    del self.titles[old.ntitle]

    def candidates(self, doc: _Doc) -> tuple[list[int], set[int]]:
        """(candidatos por shingles raros, candidatos pelo mesmo titulo), mais antigos que doc."""
        by_content: list[int] = []
        if doc.shingles:
            shared: Counter[int] = Counter()
            for s in doc.shingles:
                plist = self.postings.get(s)
                if plist:
                    shared.update(plist)
            by_content = [j for j, n in shared.items() if n >= CANDIDATE_MIN_SHARED_SHINGLES]
        by_title = set(self.titles.get(doc.ntitle, ())) if doc.title_ok else set()
        return by_content, by_title

    def add(self, doc: _Doc) -> None:
        if doc.shingles:
            for s in doc.shingles:
                plist = self.postings.setdefault(s, [])
                if len(plist) < POSTINGS_CAP:
                    plist.append(doc.idx)
            self.shingle_window.append(doc.idx)
        if doc.title_ok:
            tlist = self.titles.setdefault(doc.ntitle, [])
            if len(tlist) < TITLE_POSTINGS_CAP:
                tlist.append(doc.idx)
            self.title_window.append(doc.idx)


def _pair(older: _Doc, doc: _Doc, same_title_candidate: bool) -> _Pair:
    if older.shingles is not None and doc.shingles is not None:
        jaccard, containment, smaller = similarity(older.shingles, doc.shingles)
    else:
        jaccard, containment, smaller = 0.0, 0.0, 0
    days = (doc.ts - older.ts) / DAY_SECONDS
    title_edge = (
        same_title_candidate
        and days <= E2_MAX_DAYS
        and (
            not (older.usable and doc.usable)
            or jaccard >= E2_MIN_JACCARD
            or containment >= E2_MIN_CONTAINMENT
        )
    )
    return _Pair(jaccard, containment, smaller, days, title_edge)


def _role(ts: float, since_ts: float | None, until_ts: float | None) -> str:
    if since_ts is not None and ts < since_ts:
        return _CONTEXT
    if until_ts is not None and ts >= until_ts:
        return _LOOKAHEAD
    return _TARGET


def plan_content_keys(
    rows: Iterable[ArticleRow],
    since: datetime | None = None,
    until: datetime | None = None,
) -> ContentKeyPlan:
    """Calcula a content_key (H5) dos artigos em [since, until) a partir do stream `rows`.

    `rows` vem em ordem de (published_at, unique_id) e inclui o contexto (antes de `since`) e o
    lookahead (a partir de `until`). O contexto entra semeado pela chave gravada (NULL ou a
    propria = lider; outra = membro de outro grupo) e so e gravado quando um lider ganha o
    primeiro membro; o lookahead completa os grupos e as familias do G1 dos artigos do alvo e
    nao e gravado.
    """
    since_ts = since.timestamp() if since else None
    until_ts = until.timestamp() if until else None
    docs: list[_Doc] = []
    pairs: dict[tuple[int, int], _Pair] = {}
    window = _Window(docs)

    for row in rows:
        doc = _Doc(len(docs), row, _role(row.published_at.timestamp(), since_ts, until_ts))
        docs.append(doc)
        window.evict(doc.ts)
        by_content, by_title = window.candidates(doc)
        for j in by_title.union(by_content):
            older = docs[j]
            p = _pair(older, doc, j in by_title)
            if p.title_edge or _e1_similar(p) or _siblings(older, doc, p):
                pairs[(j, doc.idx)] = p
        window.add(doc)

    # G1: familias de modelo (>= 2 irmaos do mesmo orgao; ver _siblings)
    sibling_count: Counter[int] = Counter()
    for (j, i), p in pairs.items():
        if _siblings(docs[j], docs[i], p):
            sibling_count.update((i, j))
    family = {k for k, n in sibling_count.items() if n >= G1_MIN_SIBLINGS}

    # Arestas (E1/E2 com as guardas), vistas do artigo mais novo para os mais antigos
    earlier: dict[int, list[tuple[int, float]]] = {}
    n_edges = 0
    for (j, i), p in pairs.items():
        if _is_edge(docs[j], docs[i], p, family):
            earlier.setdefault(i, []).append((j, p.jaccard))
            n_edges += 1

    # Agrupamento por lider, em ordem de (published_at, unique_id)
    group: list[str] = []
    for doc in docs:
        if doc.role == _CONTEXT:
            group.append(doc.stored_key or doc.uid)
            continue
        best: tuple[int, float] | None = None
        for j, jaccard in earlier.get(doc.idx, ()):
            if group[j] != docs[j].uid:
                continue  # nao e lider
            if best is None or jaccard > best[1] or (jaccard == best[1] and j < best[0]):
                best = (j, jaccard)
        group.append(docs[best[0]].uid if best else doc.uid)

    size = Counter(group)
    plan = ContentKeyPlan()
    for doc in docs:
        leader = group[doc.idx]
        if doc.role == _TARGET:
            desired = leader if size[leader] >= 2 else None
        elif doc.role == _CONTEXT and leader == doc.uid and size[leader] >= 2:
            desired = doc.uid
        else:
            continue
        plan.keys[doc.uid] = desired
        if desired != doc.stored_key:
            plan.changes.append((doc.uid, desired))

    roles = Counter(doc.role for doc in docs)
    plan.stats = {
        "read": len(docs),
        "context": roles[_CONTEXT],
        "target": roles[_TARGET],
        "lookahead": roles[_LOOKAHEAD],
        "unusable": sum(1 for doc in docs if not doc.usable),
        "pairs": len(pairs),
        "family": len(family),
        "edges": n_edges,
        "grouped_target": sum(
            1 for doc in docs if doc.role == _TARGET and plan.keys.get(doc.uid) is not None
        ),
        "changes": len(plan.changes),
    }
    return plan


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------

_SELECT_ARTICLES_SQL = """
    SELECT unique_id, title, content, COALESCE(agency_key, agency_id::text) AS agency,
           published_at, content_key
    FROM news
    WHERE {where}
    ORDER BY published_at, unique_id
"""

# So toca a linha se a chave muda: cada UPDATE em news dispara o trigger de updated_at e, se nao
# for HOT, reescreve as entradas dos indices (inclusive o HNSW do embedding).
UPDATE_CONTENT_KEYS_SQL = """
    UPDATE news AS n
    SET content_key = v.content_key
    FROM (VALUES %s) AS v(unique_id, content_key)
    WHERE n.unique_id = v.unique_id
      AND n.content_key IS DISTINCT FROM v.content_key
"""
_UPDATE_TEMPLATE = "(%s, %s::text)"


def build_select_articles(
    start: datetime | None, end: datetime | None
) -> tuple[str, dict[str, datetime]]:
    """SELECT do stream em [start, end), em ordem de (published_at, unique_id)."""
    conditions: list[str] = []
    params: dict[str, datetime] = {}
    if start is not None:
        conditions.append("published_at >= %(start)s")
        params["start"] = start
    if end is not None:
        conditions.append("published_at < %(end)s")
        params["end"] = end
    where = " AND ".join(conditions) or "TRUE"
    return _SELECT_ARTICLES_SQL.format(where=where), params


def read_window(
    since: datetime | None, until: datetime | None, context_days: int
) -> tuple[datetime | None, datetime | None]:
    """Intervalo lido: contexto antes de `since` (+1 dia para completar as familias do G1 dos
    artigos do contexto) e lookahead depois de `until`: todo membro possivel de um lider do alvo
    (<= MAX_PAIR_DAYS) mais 1 dia para as familias desses membros. Sem o lookahead inteiro, um
    lider no fim do bloco perde o membro do bloco seguinte e a re-execucao alterna NULL/chave."""
    family_days = timedelta(days=G1_SIBLING_MAX_DAYS)
    start = since - timedelta(days=context_days) - family_days if since else None
    end = until + timedelta(days=MAX_PAIR_DAYS) + family_days if until else None
    return start, end


def _stream_articles(
    conn: Any, start: datetime | None, end: datetime | None
) -> Iterator[ArticleRow]:
    sql, params = build_select_articles(start, end)
    cursor = conn.cursor(name="content_keys_stream")
    cursor.itersize = FETCH_SIZE
    try:
        cursor.execute(sql, params)
        for row in cursor:
            yield ArticleRow(*row)
    finally:
        cursor.close()


def _write_changes(conn: Any, changes: list[tuple[str, str | None]]) -> int:
    from psycopg2.extras import execute_values

    updated = 0
    cursor = conn.cursor()
    try:
        for i in range(0, len(changes), UPDATE_BATCH_SIZE):
            batch = changes[i : i + UPDATE_BATCH_SIZE]
            execute_values(
                cursor,
                UPDATE_CONTENT_KEYS_SQL,
                batch,
                template=_UPDATE_TEMPLATE,
                page_size=UPDATE_BATCH_SIZE,
            )
            updated += cursor.rowcount
    finally:
        cursor.close()
    return updated


def compute_content_keys(
    conn: Any,
    since: datetime | None,
    context_days: int = CONTEXT_DAYS,
    until: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Recalcula news.content_key dos artigos com published_at em [since, until).

    `since=None` recalcula desde o inicio; `until=None`, ate o fim. Le `context_days` dias antes
    de `since` como contexto. Nao comita: a transacao e do chamador (run_content_keys, 036).
    """
    t0 = time.perf_counter()
    start, end = read_window(since, until, context_days)
    plan = plan_content_keys(_stream_articles(conn, start, end), since=since, until=until)
    updated = 0 if dry_run else _write_changes(conn, plan.changes)
    result: dict[str, Any] = {
        **plan.stats,
        "updated": updated,
        "dry_run": dry_run,
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }
    logger.info("content_keys: %s", result)
    return result


def run_content_keys(
    db_url: str, days: int = RECOMPUTE_DAYS, now: datetime | None = None
) -> dict[str, Any]:
    """Tarefa da DAG: recalcula os ultimos `days` dias numa transacao."""
    import psycopg2

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        result = compute_content_keys(conn, since=since)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
