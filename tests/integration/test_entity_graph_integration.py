"""
Integração da projeção em grafo (jobs/graph/edges.py) contra PostgreSQL real.

Aplica todas as migrações (inclusive 032 e 035) num banco descartável e roda
project_entity_graph de ponta a ponta: dedup por COALESCE(content_key, content_hash,
unique_id) nas arestas de co-menção (unique_content_count), entity_stats e
entity_graph_meta; e compute_content_keys (chave de quase-duplicata H5) gravando
news.content_key. Os testes unitários só conferem as strings de SQL e o plano.

Requer: PostgreSQL com pgvector, apontado por MIGRATION_TEST_DATABASE_URL (o mesmo
banco descartável de test_migrate_integration.py; ver ci-migrations.yaml):
    pytest tests/integration/test_entity_graph_integration.py --no-cov
"""

import json
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from data_platform.jobs.graph.content_keys import compute_content_keys, run_content_keys
from data_platform.jobs.graph.edges import project_entity_graph
from tests.integration.test_migrate_integration import (
    DATABASE_URL,
    _apply_all_migrations,
    _execute,
    _reset_database,
)


@pytest.fixture(autouse=True)
def migrated_database():
    _reset_database()
    _apply_all_migrations()
    _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC'), ('mds', 'MDS')")
    for entity_id in ("Q1", "Q2", "Q3"):
        _execute(
            "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance) "
            f"VALUES ('{entity_id}', 'Entidade {entity_id}', 'ORG', 'llm')"
        )
    yield


def _insert_article(
    unique_id: str,
    agency_key: str,
    published_at: str,
    content_hash: str | None,
    entity_ids: list[str],
    content_key: str | None = None,
) -> None:
    hash_sql = f"'{content_hash}'" if content_hash else "NULL"
    key_sql = f"'{content_key}'" if content_key else "NULL"
    _execute(
        "INSERT INTO news (unique_id, agency_id, title, published_at, agency_key, content_hash, "
        "content_key) "
        f"SELECT '{unique_id}', id, 'Título', '{published_at}', key, {hash_sql}, {key_sql} "
        f"FROM agencies WHERE key = '{agency_key}'"
    )
    entities = [{"text": e, "type": "ORG", "canonical_id": e} for e in entity_ids]
    _execute(
        "INSERT INTO news_features (unique_id, features) "
        f"VALUES ('{unique_id}', '{json.dumps({'entities': entities})}'::jsonb)"
    )


def _three_articles_two_share_content() -> None:
    """a1 e a2: a mesma matéria republicada por MEC e MDS (mesmo content_hash); a3: outra."""
    _insert_article("a1", "mec", "2026-10-01T12:00:00+00:00", "h1", ["Q1", "Q2"])
    _insert_article("a2", "mds", "2026-10-02T12:00:00+00:00", "h1", ["Q1", "Q2"])
    _insert_article("a3", "mec", "2026-10-03T12:00:00+00:00", None, ["Q1", "Q2", "Q3"])


def _co_mention_edges() -> dict[tuple[str, str], tuple[int, int, int]]:
    rows = _execute(
        "SELECT src_id, dst_id, weight, article_count, unique_content_count "
        "FROM entity_edges WHERE kind = 'co_mention'"
    )
    return {(src, dst): (w, ac, ucc) for src, dst, w, ac, ucc in rows}


def _entity_stats() -> dict[str, tuple]:
    rows = _execute(
        "SELECT entity_id, article_count, unique_content_count, first_seen, last_seen, "
        "is_generic, generic_reason FROM entity_stats"
    )
    return {row[0]: row[1:] for row in rows}


@pytest.mark.integration
class TestCoMentionDedup:
    def test_unique_content_count_colapsa_republicacao(self):
        _three_articles_two_share_content()

        project_entity_graph(DATABASE_URL)

        # weight/article_count brutos (3 artigos); conteúdos distintos: h1 + a3 = 2
        assert _co_mention_edges() == {("Q1", "Q2"): (3, 3, 2)}

    def test_content_key_prevalece_sobre_o_content_hash(self):
        """Quase-duplicata (hashes diferentes, mesma content_key) conta 1; sem chave, cai no hash."""
        _insert_article("a1", "mec", "2026-10-01T12:00:00+00:00", "h1", ["Q1", "Q2"], "a1")
        _insert_article("a2", "mds", "2026-10-02T12:00:00+00:00", "h2", ["Q1", "Q2"], "a1")
        _insert_article("a3", "mec", "2026-10-03T12:00:00+00:00", "h3", ["Q1", "Q2"])
        _insert_article("a4", "mds", "2026-10-04T12:00:00+00:00", "h3", ["Q1", "Q2"])

        result = project_entity_graph(DATABASE_URL)

        # conteúdos distintos: a1 (a1 + a2) e h3 (a3 + a4)
        assert _co_mention_edges() == {("Q1", "Q2"): (4, 4, 2)}
        assert result["total_unique_content"] == 2

    def test_conjunto_de_arestas_usa_contagem_bruta(self):
        """Republicação pura (2 artigos, 1 conteúdo) continua virando aresta (weight >= 2)."""
        _insert_article("a1", "mec", "2026-10-01T12:00:00+00:00", "h1", ["Q1", "Q2"])
        _insert_article("a2", "mds", "2026-10-02T12:00:00+00:00", "h1", ["Q1", "Q2"])

        project_entity_graph(DATABASE_URL)

        assert _co_mention_edges() == {("Q1", "Q2"): (2, 2, 1)}

    def test_unique_content_count_nunca_excede_weight(self):
        _three_articles_two_share_content()
        _insert_article("a4", "mds", "2026-10-04T12:00:00+00:00", None, ["Q2", "Q3"])

        project_entity_graph(DATABASE_URL)

        edges = _co_mention_edges()
        assert edges[("Q2", "Q3")] == (2, 2, 2)
        assert all(ucc <= w for w, _, ucc in edges.values())

    def test_arestas_subordinate_to_ficam_com_unique_content_count_nulo(self):
        _execute(
            "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance, extra) "
            """VALUES ('Q_filho', 'Secretaria', 'ORG', 'llm', '{"parent_qid": "Q1"}')"""
        )

        project_entity_graph(DATABASE_URL)

        rows = _execute(
            "SELECT src_id, dst_id, unique_content_count FROM entity_edges "
            "WHERE kind = 'subordinate_to'"
        )
        assert rows == [("Q_filho", "Q1", None)]


@pytest.mark.integration
class TestEntityStats:
    def test_contagens_bruta_e_deduplicada_por_entidade(self):
        _three_articles_two_share_content()

        result = project_entity_graph(DATABASE_URL)

        stats = _entity_stats()
        first = datetime(2026, 10, 1, 12, tzinfo=UTC)
        last = datetime(2026, 10, 3, 12, tzinfo=UTC)
        assert stats["Q1"] == (3, 2, first, last, False, None)
        assert stats["Q2"] == (3, 2, first, last, False, None)
        assert stats["Q3"] == (1, 1, last, last, False, None)
        assert result["entity_stats"] == 3

    def test_meta_totaliza_artigos_com_mencao(self):
        _three_articles_two_share_content()
        # artigo sem menção canônica não entra no universo do lift/PMI
        _execute(
            "INSERT INTO news (unique_id, agency_id, title, published_at, agency_key) "
            "SELECT 'sem_mencao', id, 'Título', '2026-10-05T12:00:00+00:00', key "
            "FROM agencies WHERE key = 'mec'"
        )

        result = project_entity_graph(DATABASE_URL)

        rows = _execute("SELECT id, total_articles, total_unique_content FROM entity_graph_meta")
        assert rows == [(1, 3, 2)]
        assert result["total_articles"] == 3
        assert result["total_unique_content"] == 2

    def test_rebuild_preserva_curadoria_e_remove_entidade_sem_mencao(self):
        _three_articles_two_share_content()
        project_entity_graph(DATABASE_URL)
        _execute(
            "UPDATE entity_stats SET is_generic = true, generic_reason = 'manual' "
            "WHERE entity_id = 'Q1'"
        )
        # a3 perde as menções: Q3 fica sem artigo, Q1/Q2 caem para 2 artigos / 1 conteúdo
        _execute("UPDATE news_features SET features = '{}'::jsonb WHERE unique_id = 'a3'")

        project_entity_graph(DATABASE_URL)

        stats = _entity_stats()
        assert set(stats) == {"Q1", "Q2"}
        assert stats["Q1"][:2] == (2, 1)
        assert stats["Q1"][4:] == (True, "manual")
        assert stats["Q2"][4:] == (False, None)
        assert _execute("SELECT total_articles, total_unique_content FROM entity_graph_meta") == [
            (2, 1)
        ]

    def test_idempotente(self):
        _three_articles_two_share_content()

        project_entity_graph(DATABASE_URL)
        first_stats, first_edges = _entity_stats(), _co_mention_edges()
        project_entity_graph(DATABASE_URL)

        assert _entity_stats() == first_stats
        assert _co_mention_edges() == first_edges
        assert _execute("SELECT count(*) FROM entity_graph_meta") == [(1,)]

    def test_corpus_sem_mencao_zera_meta(self):
        result = project_entity_graph(DATABASE_URL)

        assert _entity_stats() == {}
        assert _execute("SELECT total_articles, total_unique_content FROM entity_graph_meta") == [
            (0, 0)
        ]
        assert result["entity_stats"] == 0


# ---------------------------------------------------------------------------
# compute_content_keys (DP-1b) contra o Postgres
# ---------------------------------------------------------------------------

_BASE = " ".join(f"reforma{i}" for i in range(200))
_OUTRO = " ".join(f"outro{i}" for i in range(200))
_T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _insert_news(
    unique_id: str,
    agency_key: str,
    title: str,
    content: str,
    published_at: datetime,
    content_key: str | None = None,
) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (unique_id, agency_id, title, content, published_at, "
                "agency_key, content_key) "
                "SELECT %s, id, %s, %s, %s, key, %s FROM agencies WHERE key = %s",
                (unique_id, title, content, published_at, content_key, agency_key),
            )
        conn.commit()
    finally:
        conn.close()


def _content_keys() -> dict[str, str | None]:
    return dict(_execute("SELECT unique_id, content_key FROM news") or [])


def _compute(**kwargs) -> dict:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        result = compute_content_keys(conn, **kwargs)
        conn.commit()
        return result
    finally:
        conn.close()


def _republicacao() -> None:
    """mec publica; mds republica com URL de imagem própria (content_hash diferente)."""
    _insert_news("mec-1", "mec", "Programa amplia vagas em escolas", _BASE, _T0)
    _insert_news(
        "mds-1",
        "mds",
        "MDS detalha ampliação de vagas",
        f"![foto](https://www.gov.br/mds/a.jpg) {_BASE}",
        _T0 + timedelta(hours=3),
    )
    _insert_news("mec-2", "mec", "Outro assunto", _OUTRO, _T0 + timedelta(hours=5))


@pytest.mark.integration
class TestComputeContentKeys:
    def test_grava_o_lider_nos_membros_e_nulo_nos_isolados(self):
        _republicacao()

        result = _compute(since=None)

        assert _content_keys() == {"mec-1": "mec-1", "mds-1": "mec-1", "mec-2": None}
        assert result["changes"] == 2
        assert result["updated"] == 2

    def test_idempotente(self):
        _republicacao()
        _compute(since=None)

        second = _compute(since=None)

        assert second["changes"] == 0
        assert second["updated"] == 0

    def test_dry_run_nao_grava(self):
        _republicacao()

        result = _compute(since=None, dry_run=True)

        assert result["changes"] == 2
        assert set(_content_keys().values()) == {None}

    def test_janela_le_o_contexto_e_so_grava_o_alvo_e_o_lider_promovido(self):
        _republicacao()
        # anterior ao contexto: nunca é lido nem regravado
        _insert_news("velho", "mec", "Programa antigo", _BASE, _T0 - timedelta(days=30), "x")

        result = _compute(since=_T0 + timedelta(hours=1))

        assert _content_keys() == {
            "mec-1": "mec-1",
            "mds-1": "mec-1",
            "mec-2": None,
            "velho": "x",
        }
        assert result["context"] == 1
        assert result["target"] == 2

    def test_alimenta_o_dedup_do_grafo(self):
        _republicacao()
        entities = [{"text": e, "type": "ORG", "canonical_id": e} for e in ("Q1", "Q2")]
        for uid in ("mec-1", "mds-1", "mec-2"):
            _execute(
                "INSERT INTO news_features (unique_id, features) "
                f"VALUES ('{uid}', '{json.dumps({'entities': entities})}'::jsonb)"
            )
        _compute(since=None)

        project_entity_graph(DATABASE_URL)

        # 3 artigos; conteúdos distintos: mec-1 (com a republicação do mds) e mec-2
        assert _co_mention_edges() == {("Q1", "Q2"): (3, 3, 2)}

    def test_run_content_keys_recalcula_os_ultimos_10_dias(self):
        _republicacao()

        # since = T0 + 2 dias: tudo vira contexto, semeado como líder; nada a gravar
        result = run_content_keys(DATABASE_URL, now=_T0 + timedelta(days=12))

        assert result["target"] == 0
        assert set(_content_keys().values()) == {None}

        result = run_content_keys(DATABASE_URL, now=_T0 + timedelta(days=9))

        assert result["target"] == 3
        assert _content_keys() == {"mec-1": "mec-1", "mds-1": "mec-1", "mec-2": None}
