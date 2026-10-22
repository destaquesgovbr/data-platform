"""
Integration tests for the database migration system.

Validates that all migrations can run sequentially against a real PostgreSQL
database, are idempotent (safe to re-execute), and support rollback.

Requires: PostgreSQL with pgvector extension (docker compose up).
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
MIGRATE_SCRIPT = SCRIPTS_DIR / "migrate.py"
MIGRATIONS_DIR = SCRIPTS_DIR / "migrations"

DATABASE_URL = os.getenv(
    "MIGRATION_TEST_DATABASE_URL",
    "postgresql://test:test@localhost:5432/test_migrations",
)


def _find_concurrent_migrations() -> set[str]:
    """Detect migrations that use CONCURRENTLY (incompatible with transactions)."""
    versions = set()
    for f in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"):
        if "_rollback" in f.name:
            continue
        content = f.read_text()
        if "CONCURRENTLY" in content:
            versions.add(f.name[:3])
    return versions


# Migrations that use CREATE INDEX CONCURRENTLY cannot run inside a transaction.
# The runner wraps each migration in a transaction, so these must be applied manually.
CONCURRENT_MIGRATIONS = _find_concurrent_migrations()

BASELINE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agencies (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    type VARCHAR(100),
    parent_key VARCHAR(100),
    url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS themes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    label VARCHAR(500) NOT NULL,
    full_name VARCHAR(600),
    level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
    parent_code VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news (
    id SERIAL PRIMARY KEY,
    unique_id VARCHAR(32) UNIQUE NOT NULL,
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    theme_l1_id INTEGER REFERENCES themes(id),
    theme_l2_id INTEGER REFERENCES themes(id),
    theme_l3_id INTEGER REFERENCES themes(id),
    most_specific_theme_id INTEGER REFERENCES themes(id),
    title TEXT NOT NULL,
    url TEXT,
    image_url TEXT,
    video_url TEXT,
    category VARCHAR(500),
    tags TEXT[],
    content TEXT,
    editorial_lead TEXT,
    subtitle TEXT,
    summary TEXT,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_datetime TIMESTAMP WITH TIME ZONE,
    extracted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    agency_key VARCHAR(100),
    agency_name VARCHAR(500)
);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_news_updated_at
    BEFORE UPDATE ON news
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_news_unique_id ON news(unique_id);
CREATE INDEX IF NOT EXISTS idx_news_published_at ON news(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_agency_id ON news(agency_id);
CREATE INDEX IF NOT EXISTS idx_news_agency_key ON news(agency_key);

-- news_features é criada pela migração 004 (que aqui fica stampada, não executada).
-- O baseline precisa dela porque migrações posteriores (ex.: 018 indexa
-- features->'entities'; Fase 6 deriva dela) assumem a tabela existente.
CREATE TABLE IF NOT EXISTS news_features (
    unique_id VARCHAR(120) PRIMARY KEY REFERENCES news(unique_id) ON DELETE CASCADE,
    features JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(20) PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""


def _run_migrate(*args: str, needs_db: bool = True) -> subprocess.CompletedProcess:
    """Run the migrate.py script with given arguments."""
    cmd = [sys.executable, str(MIGRATE_SCRIPT), *args]
    if needs_db:
        cmd.extend(["--db-url", DATABASE_URL])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _apply_concurrent_migration(version: str):
    """Apply a CONCURRENTLY migration outside a transaction, then stamp it."""
    migration_file = next(MIGRATIONS_DIR.glob(f"{version}_*.sql"))
    sql = migration_file.read_text()
    # Remove CONCURRENTLY keyword so it can run in normal mode for testing
    sql_without_concurrent = sql.replace(" CONCURRENTLY", "")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql_without_concurrent)
    cur.close()
    conn.close()

    _run_migrate("stamp", version, "--yes")


def _reset_database():
    """Drop and recreate the test database schema."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(BASELINE_SQL)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def fresh_database():
    """Reset database to baseline state before each test."""
    _reset_database()
    yield


def _apply_all_migrations():
    """Apply all migrations in 3 phases to handle CONCURRENTLY limitations.

    Phase 1: Apply migrations up to the first CONCURRENTLY one via runner.
    Phase 2: Apply each CONCURRENTLY migration manually (outside transaction) + stamp.
    Phase 3: Apply remaining migrations via runner.
    """
    if not CONCURRENT_MIGRATIONS:
        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Migration failed:\n{result.stdout}\n{result.stderr}"
        return

    # Find the first CONCURRENTLY migration to determine target
    sorted_concurrent = sorted(CONCURRENT_MIGRATIONS)
    first_concurrent = sorted_concurrent[0]
    # Apply everything before the first CONCURRENTLY migration
    before_target = f"{int(first_concurrent) - 1:03d}"
    result = _run_migrate("migrate", "--target", before_target, "--yes")
    assert result.returncode == 0, f"Migration failed:\n{result.stdout}\n{result.stderr}"

    # Apply each CONCURRENTLY migration manually
    for version in sorted_concurrent:
        _apply_concurrent_migration(version)

    # Apply remaining migrations
    result = _run_migrate("migrate", "--yes")
    if result.returncode != 0:
        assert "No pending migrations" in result.stdout or result.returncode == 0, (
            f"Migration failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.mark.integration
class TestMigrationSequence:
    """Test full migration sequence on a real database."""

    def test_full_sequence_on_clean_db(self):
        """All migrations run without error on baseline schema."""
        _apply_all_migrations()

        result = _run_migrate("status")
        assert result.returncode == 0
        assert "Pending: 0" in result.stdout

    def test_status_shows_zero_pending_after_migrate(self):
        """After applying all migrations, status shows nothing pending."""
        _apply_all_migrations()

        result = _run_migrate("status")
        assert result.returncode == 0
        assert "Pending: 0" in result.stdout

    def test_idempotency_double_run(self):
        """Running migrate twice is safe — second run is a no-op."""
        _apply_all_migrations()

        second = _run_migrate("migrate", "--yes")
        assert second.returncode == 0
        assert "No pending migrations" in second.stdout

    def test_validate_after_full_sequence(self):
        """Validate passes after all migrations are applied."""
        _apply_all_migrations()

        result = _run_migrate("validate", needs_db=False)
        assert result.returncode == 0
        assert "consistent" in result.stdout

    def test_rollback_last_and_reapply(self):
        """Rollback of last non-concurrent migration + re-apply works."""
        _apply_all_migrations()

        # Find the last non-CONCURRENTLY migration with a rollback file
        all_migrations = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*"))
        candidates = [
            m
            for m in all_migrations
            if m.name[:3] not in CONCURRENT_MIGRATIONS
            and not m.name.endswith("_rollback.sql")
            and not m.suffix == ".py"
        ]
        rollback_target = None
        for m in reversed(candidates):
            version = m.name[:3]
            if list(MIGRATIONS_DIR.glob(f"{version}_*_rollback.sql")):
                rollback_target = version
                break

        if not rollback_target:
            pytest.skip("No non-concurrent SQL migration with rollback file found")

        result = _run_migrate("rollback", rollback_target, "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0
        assert "migration(s) processed" in result.stdout

    def test_migrate_after_manual_application(self):
        """Migration applied manually (no history) is re-executed safely (idempotent)."""
        # Apply migrations 001-007 via runner
        result = _run_migrate("migrate", "--target", "007", "--yes")
        assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"

        # Apply migration 008 SQL directly (simulating DBA in Cloud Console)
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                sql = (MIGRATIONS_DIR / "008_create_scrape_runs.sql").read_text()
                cur.execute(sql)
            conn.commit()
        finally:
            conn.close()

        # Verify: table exists but NO history record for 008
        conn = psycopg2.connect(DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'scrape_runs')"
                )
                assert cur.fetchone()[0] is True
                cur.execute(
                    "SELECT COUNT(*) FROM migration_history "
                    "WHERE version = '008' AND operation = 'migrate' "
                    "AND status = 'success'"
                )
                assert cur.fetchone()[0] == 0
        finally:
            conn.close()

        # Run migrate — should detect 008 as pending, re-execute (no-op), succeed
        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Migrate failed:\n{result.stdout}\n{result.stderr}"
        assert "failed" not in result.stdout.lower()

        # Verify: status shows 0 pending (all migrations applied)
        result = _run_migrate("status")
        assert result.returncode == 0
        assert "Pending: 0" in result.stdout

    def test_stamp_then_migrate(self):
        """Stamp first N migrations, then migrate applies only the rest."""
        result = _run_migrate("stamp", "007", "--yes")
        assert result.returncode == 0
        assert "stamped" in result.stdout.lower()

        # Apply remaining (handling CONCURRENTLY ones)
        if CONCURRENT_MIGRATIONS:
            for version in sorted(CONCURRENT_MIGRATIONS):
                if int(version) > 7:
                    # Apply up to before the concurrent migration
                    before = f"{int(version) - 1:03d}"
                    _run_migrate("migrate", "--target", before, "--yes")
                    _apply_concurrent_migration(version)
            _run_migrate("migrate", "--yes")
        else:
            result = _run_migrate("migrate", "--yes")
            assert result.returncode == 0

        result = _run_migrate("status")
        assert "Pending: 0" in result.stdout


def _execute(sql: str) -> list[tuple] | None:
    """Run SQL in its own transaction and return the rows, if any."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall() if cur.description else None
        conn.commit()
        return rows
    finally:
        conn.close()


@pytest.mark.integration
class TestPolicyGazetteerMigrations:
    """027 (seed do gazetteer de políticas) e 028 (remoção das POLICYs órfãs)."""

    def test_028_removes_orphan_gazetteer_policies(self):
        _apply_all_migrations()

        rows = _execute("SELECT count(*) FROM entity_registry WHERE provenance = 'gazetteer'")
        assert rows == [(0,)]

    def test_028_keeps_gazetteer_policy_with_references(self):
        _apply_all_migrations()
        _execute(
            "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance) VALUES "
            "('dgb_usada', 'Usada', 'POLICY', 'gazetteer'), "
            "('dgb_orfa', 'Órfã', 'POLICY', 'gazetteer')"
        )
        _execute(
            "INSERT INTO entity_alias (alias_norm, type, entity_id, source) "
            "VALUES ('usada', 'POLICY', 'dgb_usada', 'manual')"
        )

        _execute((MIGRATIONS_DIR / "028_remove_orphan_gazetteer_policies.sql").read_text())

        rows = _execute("SELECT entity_id FROM entity_registry WHERE provenance = 'gazetteer'")
        assert rows == [("dgb_usada",)]

    def test_027_rollback_only_touches_gazetteer_policies(self):
        _apply_all_migrations()
        _execute(
            "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance, extra) VALUES "
            "('dgb_pe-de-meia', 'Pé-de-Meia', 'POLICY', 'llm', "
            """'{"domain": "SOCIAL", "lifecycle_phase": "ROUTINE"}'), """
            "('dgb_outra-politica', 'Outra', 'POLICY', 'llm', "
            """'{"domain": "HEALTH", "lifecycle_phase": "ROUTINE"}')"""
        )

        result = _run_migrate("rollback", "027", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        extra = dict(_execute("SELECT entity_id, extra FROM entity_registry WHERE type = 'POLICY'"))
        assert "domain" not in extra["dgb_pe-de-meia"]
        assert extra["dgb_outra-politica"] == {"domain": "HEALTH", "lifecycle_phase": "ROUTINE"}


def _columns(table: str) -> dict[str, tuple[str, str]]:
    """{coluna: (data_type, is_nullable)} de uma tabela do schema public."""
    rows = _execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND table_name = '{table}'"
    )
    return {name: (dtype, nullable) for name, dtype, nullable in rows or []}


@pytest.mark.integration
class TestEntityTrendingBaselineMigration:
    """029: baseline_count/baseline_agencies em entity_trending_scores (Fase 2.5, F2)."""

    def test_029_adiciona_colunas_baseline_nulas(self):
        _apply_all_migrations()

        cols = _columns("entity_trending_scores")
        assert cols["baseline_count"] == ("integer", "YES")
        assert cols["baseline_agencies"] == ("integer", "YES")

    def test_029_nao_cria_indice(self):
        """Com o DELETE por execução a tabela guarda um único snapshot: índice é desnecessário."""
        _apply_all_migrations()

        rows = _execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'entity_trending_scores'"
        )
        assert {r[0] for r in rows} == {"entity_trending_scores_pkey", "idx_entity_trending_score"}

    def test_029_insert_legado_sem_baseline_continua_valido(self):
        """O persist anterior lista colunas explícitas; a 029 não pode quebrá-lo."""
        _apply_all_migrations()
        _execute(
            "INSERT INTO entity_trending_scores (entity_id, canonical_name, type, "
            "trending_score, volume_ratio, window_count, window_agencies) "
            "VALUES ('Q1', 'Org', 'ORG', 1.0, 2.0, 3, 2)"
        )

        rows = _execute("SELECT baseline_count, baseline_agencies FROM entity_trending_scores")
        assert rows == [(None, None)]

    def test_029_rollback_remove_colunas_e_reaplica(self):
        _apply_all_migrations()

        result = _run_migrate("rollback", "029", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"
        cols = _columns("entity_trending_scores")
        assert "baseline_count" not in cols
        assert "baseline_agencies" not in cols

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Re-apply failed:\n{result.stdout}\n{result.stderr}"
        assert {"baseline_count", "baseline_agencies"} <= set(_columns("entity_trending_scores"))


@pytest.mark.integration
class TestEntityStatsMigration:
    """032: entity_stats, entity_graph_meta e entity_edges.unique_content_count (DP-1).

    Contrato lido pela graphql-api (GQL-1) via LEFT JOIN: nomes e tipos fixos.
    """

    def test_032_adiciona_unique_content_count_nulo_em_entity_edges(self):
        _apply_all_migrations()

        assert _columns("entity_edges")["unique_content_count"] == ("integer", "YES")

    def test_032_cria_entity_stats_com_o_contrato(self):
        _apply_all_migrations()

        assert _columns("entity_stats") == {
            "entity_id": ("character varying", "NO"),
            "article_count": ("integer", "NO"),
            "unique_content_count": ("integer", "NO"),
            "first_seen": ("timestamp with time zone", "YES"),
            "last_seen": ("timestamp with time zone", "YES"),
            "is_generic": ("boolean", "NO"),
            "generic_reason": ("text", "YES"),
            "computed_at": ("timestamp with time zone", "NO"),
        }

    def test_032_cria_entity_graph_meta_com_o_contrato(self):
        _apply_all_migrations()

        assert _columns("entity_graph_meta") == {
            "id": ("smallint", "NO"),
            "total_articles": ("integer", "NO"),
            "total_unique_content": ("integer", "NO"),
            "computed_at": ("timestamp with time zone", "NO"),
        }

    def test_032_entity_graph_meta_so_aceita_id_1(self):
        _apply_all_migrations()
        _execute(
            "INSERT INTO entity_graph_meta (id, total_articles, total_unique_content) VALUES (1, 0, 0)"
        )

        with pytest.raises(psycopg2.errors.CheckViolation):
            _execute(
                "INSERT INTO entity_graph_meta (id, total_articles, total_unique_content) "
                "VALUES (2, 0, 0)"
            )

    def test_032_defaults_de_entity_stats_e_cascade_do_registry(self):
        _apply_all_migrations()
        _execute(
            "INSERT INTO entity_registry (entity_id, canonical_name, type, provenance) "
            "VALUES ('Q1', 'Org', 'ORG', 'llm')"
        )
        _execute(
            "INSERT INTO entity_stats (entity_id, article_count, unique_content_count) "
            "VALUES ('Q1', 3, 2)"
        )
        rows = _execute(
            "SELECT is_generic, generic_reason, computed_at IS NOT NULL FROM entity_stats"
        )
        assert rows == [(False, None, True)]

        _execute("DELETE FROM entity_registry WHERE entity_id = 'Q1'")
        assert _execute("SELECT count(*) FROM entity_stats") == [(0,)]

    def test_032_entity_stats_exige_entidade_do_registry(self):
        _apply_all_migrations()

        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            _execute(
                "INSERT INTO entity_stats (entity_id, article_count, unique_content_count) "
                "VALUES ('Q_inexistente', 1, 1)"
            )

    def test_032_rollback_remove_tudo_e_reaplica(self):
        _apply_all_migrations()

        result = _run_migrate("rollback", "032", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"
        assert _columns("entity_stats") == {}
        assert _columns("entity_graph_meta") == {}
        assert "unique_content_count" not in _columns("entity_edges")

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Re-apply failed:\n{result.stdout}\n{result.stderr}"
        assert "unique_content_count" in _columns("entity_edges")
        assert "is_generic" in _columns("entity_stats")


def _indexes(table: str) -> dict[str, str]:
    """{nome do índice: definição} de uma tabela do schema public."""
    rows = _execute(f"SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '{table}'")
    return dict(rows or [])


@pytest.mark.integration
class TestNewsContentKeyMigration:
    """035: news.content_key, a chave de quase-duplicata (DP-1b).

    Contrato lido por ARTICLE_CONTENT_KEY_SQL (jobs/graph/edges.py) e pela graphql-api (GQL-1b):
    COALESCE(n.content_key, n.content_hash, n.unique_id).
    """

    def test_035_adiciona_content_key_texto_nulo(self):
        _apply_all_migrations()

        assert _columns("news")["content_key"] == ("text", "YES")

    def test_035_artigos_existentes_ficam_sem_chave(self):
        result = _run_migrate("migrate", "--target", "033", "--yes")
        assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"
        _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")
        _execute(
            "INSERT INTO news (unique_id, agency_id, title, published_at) "
            "SELECT 'antigo', id, 'Título', NOW() FROM agencies WHERE key = 'mec'"
        )

        _apply_all_migrations()

        assert _execute("SELECT content_key FROM news WHERE unique_id = 'antigo'") == [(None,)]

    def test_035_nao_indexa_content_key(self):
        """Sem índice na coluna, o UPDATE da chave pode ser HOT (não toca o HNSW do embedding)."""
        _apply_all_migrations()

        assert not [d for d in _indexes("news").values() if "content_key" in d]

    def test_035_rollback_remove_coluna_e_reaplica(self):
        _apply_all_migrations()

        result = _run_migrate("rollback", "035", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"
        assert "content_key" not in _columns("news")

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Re-apply failed:\n{result.stdout}\n{result.stderr}"
        assert _columns("news")["content_key"] == ("text", "YES")


_TEXTO_LONGO = (
    "O Ministério da Educação anunciou nesta segunda-feira a ampliação do "
    "programa de bolsas para estudantes de baixa renda em todo o país."
)


def _load_migration_033():
    import importlib.util

    path = MIGRATIONS_DIR / "033_backfill_readability_flesch_ptbr.py"
    spec = importlib.util.spec_from_file_location("migration_033", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert_news(unique_id: str, content: str | None) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (unique_id, agency_id, title, content, published_at) "
                "SELECT %s, id, 'Título', %s, NOW() FROM agencies WHERE key = 'mec'",
                (unique_id, content),
            )
        conn.commit()
    finally:
        conn.close()


def _features() -> dict[str, dict]:
    return dict(_execute("SELECT unique_id, features FROM news_features") or [])


def _run_033(dry_run: bool = False, batch_size: int | None = None) -> dict:
    module = _load_migration_033()
    if batch_size:
        module.BATCH_SIZE = batch_size
    conn = psycopg2.connect(DATABASE_URL)
    try:
        result = module.migrate(conn, dry_run=dry_run)
        conn.commit()
        return result
    finally:
        conn.close()


@pytest.mark.integration
class TestBackfillFleschPtbrMigration:
    """033: backfill de readability_flesch_ptbr nas linhas existentes de news_features (DP-1).

    Só UPDATE: notícia sem linha em news_features fica de fora (não ganha linha nova).
    """

    @pytest.fixture(autouse=True)
    def _corpus(self):
        from data_platform.workers.feature_worker.features import (
            compute_readability_flesch_ptbr,
        )

        _apply_all_migrations()
        _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")
        _insert_news("a_com_features", _TEXTO_LONGO)
        _insert_news("b_sem_linha", _TEXTO_LONGO + " Segunda frase do texto.")
        _insert_news("c_curto", "Texto curto.")
        _insert_news("d_ja_tem", _TEXTO_LONGO)
        _insert_news("e_sem_content", None)
        _insert_news("f_com_features", _TEXTO_LONGO + " Segunda frase do texto.")
        _execute(
            "INSERT INTO news_features (unique_id, features) VALUES "
            """('a_com_features', '{"word_count": 22, "readability_flesch": 38.38}'), """
            """('c_curto', '{"word_count": 2}'), """
            """('d_ja_tem', '{"readability_flesch_ptbr": 999}'), """
            """('e_sem_content', '{}'), """
            """('f_com_features', '{}')"""
        )
        self.expected_a = compute_readability_flesch_ptbr(_TEXTO_LONGO)
        self.expected_f = compute_readability_flesch_ptbr(_TEXTO_LONGO + " Segunda frase do texto.")

    def test_033_grava_a_chave_preservando_as_demais(self):
        result = _run_033()

        features = _features()
        assert features["a_com_features"] == {
            "word_count": 22,
            "readability_flesch": 38.38,
            "readability_flesch_ptbr": self.expected_a,
        }
        assert features["f_com_features"] == {"readability_flesch_ptbr": self.expected_f}
        assert features["c_curto"] == {"word_count": 2}
        assert features["e_sem_content"] == {}
        assert features["d_ja_tem"] == {"readability_flesch_ptbr": 999}
        assert result["rows_updated"] == 2
        assert result["too_short"] == 1

    def test_033_nao_cria_linha_para_noticia_sem_features(self):
        """Decisão: as ~153,8 mil notícias sem linha em news_features ficam de fora."""
        result = _run_033()

        assert "b_sem_linha" not in _features()
        assert len(_features()) == 5
        assert result["scanned"] == 3

    def test_033_pagina_em_lotes_pequenos(self):
        result = _run_033(batch_size=1)

        features = _features()
        assert features["a_com_features"]["readability_flesch_ptbr"] == self.expected_a
        assert features["f_com_features"]["readability_flesch_ptbr"] == self.expected_f
        assert "b_sem_linha" not in features
        assert result["scanned"] == 3

    def test_033_retomavel(self):
        _run_033()
        second = _run_033()

        # só o texto curto volta a ser lido (nunca ganha a chave)
        assert second["rows_updated"] == 0
        assert second["scanned"] == 1

    def test_033_dry_run_projeta_sem_gravar(self):
        result = _run_033(dry_run=True)

        assert result["preview"] is True
        assert result["pending"] == 3
        assert result["sample_size"] == 3
        assert "readability_flesch_ptbr" not in _features()["a_com_features"]

    def test_033_rollback_remove_so_a_chave(self):
        _run_033()

        result = _run_migrate("rollback", "033", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        features = _features()
        assert features["a_com_features"] == {"word_count": 22, "readability_flesch": 38.38}
        assert features["f_com_features"] == {}
        assert features["d_ja_tem"] == {}
        assert "b_sem_linha" not in features


def _load_migration_036():
    import importlib.util

    path = MIGRATIONS_DIR / "036_backfill_news_content_key.py"
    spec = importlib.util.spec_from_file_location("migration_036", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_036(dry_run: bool = False, chunk_days: int | None = None) -> dict:
    module = _load_migration_036()
    if chunk_days:
        module.CHUNK_DAYS = chunk_days
    conn = psycopg2.connect(DATABASE_URL)
    try:
        result = module.migrate(conn, dry_run=dry_run)
        conn.commit()
        return result
    finally:
        conn.close()


_REPUBLICADO = " ".join(f"reforma{i}" for i in range(200))


def _insert_full_news(
    unique_id: str, agency_key: str, title: str, content: str, published_at: str
) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (unique_id, agency_id, title, content, published_at, agency_key) "
                "SELECT %s, id, %s, %s, %s, key FROM agencies WHERE key = %s",
                (unique_id, title, content, published_at, agency_key),
            )
        conn.commit()
    finally:
        conn.close()


def _content_keys() -> dict[str, str | None]:
    return dict(_execute("SELECT unique_id, content_key FROM news") or [])


_CHAVES_ESPERADAS = {
    "antigo-mec": "antigo-mec",
    "antigo-mds": "antigo-mec",
    "virada-mec": "virada-mec",
    "virada-mds": "virada-mec",
    "isolado": None,
}


@pytest.mark.integration
class TestBackfillContentKeyMigration:
    """036: backfill de news.content_key (chave de quase-duplicata H5) no corpus inteiro."""

    @pytest.fixture(autouse=True)
    def _corpus(self):
        _apply_all_migrations()
        _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC'), ('mds', 'MDS')")
        # republicação antiga (2015), uma que atravessa a virada de dia e um texto isolado
        _insert_full_news(
            "antigo-mec", "mec", "Programa amplia vagas", _REPUBLICADO, "2015-03-10T12:00:00+00"
        )
        _insert_full_news(
            "antigo-mds",
            "mds",
            "MDS detalha vagas",
            f"![foto](https://www.gov.br/mds/a.jpg) {_REPUBLICADO}",
            "2015-03-10T15:00:00+00",
        )
        _insert_full_news(
            "virada-mec", "mec", "Outro programa novo", _REPUBLICADO, "2026-10-01T12:00:00+00"
        )
        _insert_full_news(
            "virada-mds", "mds", "Republicação do programa", _REPUBLICADO, "2026-10-02T13:00:00+00"
        )
        _insert_full_news(
            "isolado",
            "mec",
            "Assunto sem relação",
            " ".join(f"z{i}" for i in range(200)),
            "2026-10-05T12:00:00+00",
        )

    def test_036_grava_o_lider_nos_grupos_e_nulo_nos_isolados(self):
        result = _run_036()

        assert _content_keys() == _CHAVES_ESPERADAS
        assert result["rows_updated"] == 4
        assert result["grouped"] == 4
        assert result["target"] == 5

    def test_036_blocos_de_um_dia_dao_o_mesmo_resultado(self):
        """A republicação de 01→02/10 atravessa o bloco: o contexto semeado a junta."""
        result = _run_036(chunk_days=1)

        assert _content_keys() == _CHAVES_ESPERADAS
        # 2015 + (01/10 12h) + (02/10 13h) + o último, aberto; os buracos são pulados
        assert result["chunks"] == 4

    def test_036_pula_os_anos_sem_artigo(self):
        assert _run_036()["chunks"] == 2

    def test_036_idempotente(self):
        _run_036()
        second = _run_036()

        assert second["rows_updated"] == 0
        assert _content_keys() == _CHAVES_ESPERADAS

    def test_036_dry_run_projeta_sem_gravar(self):
        result = _run_036(dry_run=True)

        assert result["preview"] is True
        assert result["total_articles"] == 5
        assert result["sample_target"] == 3  # últimos SAMPLE_DAYS dias
        assert result["sample_changes"] == 2
        assert result["projected_changes"] == round(2 / 3 * 5)
        assert result["projected_seconds"] >= 0
        assert set(_content_keys().values()) == {None}

    def test_036_dry_run_sem_a_035_avisa_em_vez_de_quebrar(self):
        """`migrate --dry-run` com 035 e 036 pendentes: o runner desfaz o preview da 035."""
        result = _run_migrate("rollback", "035", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        result = _run_036(dry_run=True)

        assert result["preview"] is True
        assert "035" in result["message"]

    def test_036_corpus_vazio(self):
        _execute("DELETE FROM news")

        assert _run_036()["rows_updated"] == 0

    def test_036_rollback_limpa_as_chaves(self):
        _run_036()

        result = _run_migrate("rollback", "036", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"

        assert set(_content_keys().values()) == {None}
