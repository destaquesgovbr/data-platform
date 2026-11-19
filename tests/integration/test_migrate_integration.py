"""
Integration tests for the database migration system.

Validates that all migrations can run sequentially against a real PostgreSQL
database, are idempotent (safe to re-execute), and support rollback.

Requires: PostgreSQL with pgvector extension (docker compose up).
"""

import os
import re
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
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


def _run_migrate(
    *args: str, needs_db: bool = True, timeout: float = 120
) -> subprocess.CompletedProcess:
    """Run the migrate.py script with given arguments."""
    cmd = [sys.executable, str(MIGRATE_SCRIPT), *args]
    if needs_db:
        cmd.extend(["--db-url", DATABASE_URL])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


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


# INSERT do scraper antes da 037 (record_scrape_run em postgres_manager.py): colunas nomeadas,
# sem articles_new.
_INSERT_SCRAPE_RUN_LEGADO = (
    "INSERT INTO scrape_runs (agency_key, status, error_category, error_message, "
    "articles_scraped, articles_saved, execution_time_seconds, scraped_at, fallback_triggered) "
    "VALUES ('{agency}', 'success', NULL, NULL, 12, 12, 3.5, NOW(), false)"
)


@pytest.mark.integration
class TestScrapeRunsArticlesNewMigration:
    """037: scrape_runs.articles_new, as notícias realmente novas de cada chamada (Passo 1).

    articles_saved continua "linhas gravadas" (inserções + atualizações). Lido pelo scraper
    (agências sem notícias e relatório de cobertura) como COALESCE(articles_new, articles_saved).
    """

    def test_037_adiciona_articles_new_inteiro_nulo(self):
        _apply_all_migrations()

        assert _columns("scrape_runs")["articles_new"] == ("integer", "YES")

    def test_037_execucoes_existentes_ficam_nulas(self):
        """Sem default: NULL é "não medido", não "zero notícias novas"."""
        result = _run_migrate("migrate", "--target", "036", "--yes")
        assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"
        _execute(_INSERT_SCRAPE_RUN_LEGADO.format(agency="mec"))

        _apply_all_migrations()

        rows = _execute("SELECT articles_saved, articles_new FROM scrape_runs")
        assert rows == [(12, None)]

    def test_037_insert_legado_continua_valido(self):
        """O scraper em produção nomeia as colunas: segue gravando, com articles_new nulo."""
        _apply_all_migrations()
        _execute(_INSERT_SCRAPE_RUN_LEGADO.format(agency="mec"))
        _execute(
            "INSERT INTO scrape_runs (agency_key, status, articles_scraped, articles_saved, "
            "articles_new) VALUES ('agencia_brasil', 'success', 40, 40, 3)"
        )

        rows = _execute("SELECT agency_key, articles_new FROM scrape_runs ORDER BY agency_key")
        assert rows == [("agencia_brasil", 3), ("mec", None)]

    def test_037_indice_parcial_espelha_o_da_008(self):
        """Mesmas colunas e predicado do idx_scrape_runs_success_articles, sobre articles_new."""
        _apply_all_migrations()

        indexes = _indexes("scrape_runs")
        espelho = (
            indexes["idx_scrape_runs_success_articles"]
            .replace("idx_scrape_runs_success_articles", "idx_scrape_runs_success_articles_new")
            .replace("articles_saved", "articles_new")
        )
        assert indexes["idx_scrape_runs_success_articles_new"] == espelho

    def test_037_comenta_a_coluna(self):
        _apply_all_migrations()

        rows = _execute(
            "SELECT col_description('scrape_runs'::regclass, attnum) FROM pg_attribute "
            "WHERE attrelid = 'scrape_runs'::regclass AND attname = 'articles_new'"
        )
        assert "inseridas em news" in rows[0][0]
        assert "NULL" in rows[0][0]

    def test_037_rollback_remove_coluna_e_indice_e_reaplica(self):
        _apply_all_migrations()

        result = _run_migrate("rollback", "037", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"
        assert "articles_new" not in _columns("scrape_runs")
        assert "idx_scrape_runs_success_articles_new" not in _indexes("scrape_runs")
        assert "idx_scrape_runs_success_articles" in _indexes("scrape_runs")

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Re-apply failed:\n{result.stdout}\n{result.stderr}"
        assert _columns("scrape_runs")["articles_new"] == ("integer", "YES")
        assert "idx_scrape_runs_success_articles_new" in _indexes("scrape_runs")

    @pytest.mark.parametrize(
        ("comando", "aplicada_antes"),
        [(("migrate", "--target", "037"), False), (("rollback", "037"), True)],
        ids=["migrate", "rollback"],
    )
    def test_037_desiste_do_lock_em_vez_de_enfileirar_o_scraper(self, comando, aplicada_antes):
        """lock_timeout: atrás de uma transação aberta em scrape_runs a 037 falha inteira.

        Sem ele o pedido de ACCESS EXCLUSIVE esperaria sem prazo, e todo INSERT do scraper e
        toda leitura do monitor entrariam na fila atrás dele.
        """
        if aplicada_antes:
            _apply_all_migrations()
        else:
            result = _run_migrate("migrate", "--target", "036", "--yes")
            assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"

        leitor = psycopg2.connect(DATABASE_URL)
        try:
            with leitor.cursor() as cur:
                # ACCESS SHARE até o fim da transação, como um SELECT do monitor em andamento.
                cur.execute("SELECT count(*) FROM scrape_runs")
            inicio = time.monotonic()
            try:
                result = _run_migrate(*comando, "--yes", timeout=60)
            except subprocess.TimeoutExpired:
                pytest.fail(f"`{' '.join(comando)}` esperou o lock sem prazo (sem lock_timeout)")
            espera = time.monotonic() - inicio
        finally:
            leitor.rollback()
            leitor.close()

        assert result.returncode != 0
        assert "lock timeout" in result.stdout + result.stderr
        assert espera < 45
        assert ("articles_new" in _columns("scrape_runs")) is aplicada_antes

        # Sem a transação concorrente a mesma operação passa.
        result = _run_migrate(*comando, "--yes")
        assert result.returncode == 0, f"Retry failed:\n{result.stdout}\n{result.stderr}"
        assert ("articles_new" in _columns("scrape_runs")) is not aplicada_antes


# Contrato da 038 (desenho dos Passos 2–4, §1): o scraper-api (state/repository.py), o /dispatch
# e o painel do infra-health dependem destes nomes, tipos e nulidades.
_TSTZ = "timestamp with time zone"
_SCRAPE_AGENCY_STATE_CONTRATO = {
    "agency_key": ("text", "NO"),
    "tier": ("text", "NO"),
    "poll_interval_minutes": ("integer", "NO"),
    "rate_ewma_per_day": ("double precision", "YES"),
    "tier_updated_at": (_TSTZ, "YES"),
    "next_due_at": (_TSTZ, "NO"),
    "boost_until": (_TSTZ, "YES"),
    "last_dispatched_at": (_TSTZ, "YES"),
    "last_attempt_at": (_TSTZ, "YES"),
    "last_success_at": (_TSTZ, "YES"),
    "last_new_article_at": (_TSTZ, "YES"),
    "consecutive_permanent_failures": ("integer", "NO"),
    "consecutive_transient_failures": ("integer", "NO"),
    "failure_streak_started_at": (_TSTZ, "YES"),
    "circuit_state": ("text", "NO"),
    "circuit_opened_at": (_TSTZ, "YES"),
    "circuit_failed_probes": ("integer", "NO"),
    "last_error_category": ("text", "YES"),
    "last_error_message": ("text", "YES"),
    "created_at": (_TSTZ, "NO"),
    "updated_at": (_TSTZ, "NO"),
}

_MIGRATION_038 = MIGRATIONS_DIR / "038_create_scrape_agency_state.sql"

# Agências do cenário do seed com execução nos últimos 7 dias.
_SEMEADAS = {"agencia_brasil", "saude", "gestao", "ibama", "mec", "antaq", "ansn"}

# Notícias da ibama por idade do dia (0 = ontem), até o dia mais antigo da janela (27).
_IBAMA_POR_IDADE = {0: 4, 2: 2, 9: 7, 26: 5, 27: 9}


def _execute_com(sql: str, params: tuple) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def _hoje_brt() -> date:
    """Hoje em BRT pelo relógio do banco, o mesmo que a 038 usa."""
    return _execute("SELECT (NOW() AT TIME ZONE 'America/Sao_Paulo')::date")[0][0]


def _ewma_esperada(por_idade: dict[int, int]) -> float:
    """sum(n_d * w_d) / sum(w_d), w_d = 0.5 ** (idade / 7), nos 28 dias (0 nos sem notícia)."""
    pesos = [0.5 ** (idade / 7) for idade in range(28)]
    return sum(n * pesos[idade] for idade, n in por_idade.items()) / sum(pesos)


def _faixa(taxa: float) -> tuple[str, int]:
    if taxa >= 5:
        return "m30", 30
    if taxa >= 1:
        return "h2", 120
    if taxa >= 0.2:
        return "h6", 360
    return "d1", 1440


def _noticias(agency: str, dia: date, qtd: int, hora: str = "12:00") -> None:
    """`qtd` notícias da agência publicadas em `dia` às `hora` de Brasília."""
    _execute_com(
        "INSERT INTO news (unique_id, agency_id, agency_key, title, published_at) "
        "SELECT %(prefixo)s || g, a.id, %(agency)s, 'Título', "
        "(%(dia)s::date + %(hora)s::time) AT TIME ZONE 'America/Sao_Paulo' "
        "FROM agencies AS a CROSS JOIN generate_series(1, %(qtd)s) AS g "
        "WHERE a.key = %(agency)s",
        {
            "prefixo": f"{agency}-{dia.isoformat()}-{hora}-",
            "agency": agency,
            "dia": dia,
            "hora": hora,
            "qtd": qtd,
        },
    )


def _execucao(
    agency: str,
    quando: datetime,
    status: str = "success",
    categoria: str | None = None,
    mensagem: str | None = None,
) -> None:
    _execute_com(
        "INSERT INTO scrape_runs (agency_key, status, error_category, error_message, scraped_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (agency, status, categoria, mensagem, quando),
    )


def _cenario_do_seed() -> datetime:
    """Banco na 037 com histórico de news e scrape_runs; devolve o "agora" das execuções."""
    result = _run_migrate("migrate", "--target", "037", "--yes")
    assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"
    _execute(
        "INSERT INTO agencies (key, name) VALUES ('agencia_brasil', 'Agência Brasil'), "
        "('saude', 'Saúde'), ('gestao', 'Gestão'), ('ibama', 'Ibama'), ('mec', 'MEC'), "
        "('antaq', 'Antaq'), ('sudam', 'Sudam'), ('planalto', 'Planalto')"
    )
    hoje = _hoje_brt()

    def dia(idade: int) -> date:
        return hoje - timedelta(days=idade + 1)

    # agencia_brasil: 10 por dia nos 28 dias. Hoje (parcial) e o 29º dia ficam fora da janela.
    for idade in range(28):
        _noticias("agencia_brasil", dia(idade), 10)
    _noticias("agencia_brasil", hoje, 50, "00:30")
    _noticias("agencia_brasil", dia(28), 100, "23:00")
    # saude: 2 por dia.
    for idade in range(28):
        _noticias("saude", dia(idade), 2)
    # gestao: 3 ontem; a das 22:30 de Brasília já é hoje em UTC e conta como ontem.
    _noticias("gestao", dia(0), 2)
    _noticias("gestao", dia(0), 1, "22:30")
    for idade, qtd in _IBAMA_POR_IDADE.items():
        _noticias("ibama", dia(idade), qtd)
    # Com notícias, mas sem execução nos últimos 7 dias: fora do seed.
    _noticias("sudam", dia(1), 5)
    _noticias("planalto", dia(1), 5)

    agora = datetime.now(UTC)
    # agencia_brasil: falha passageira e depois sucesso, que limpa o último erro.
    _execucao("agencia_brasil", agora - timedelta(hours=3), "error", "network_error", "timeout")
    _execucao("agencia_brasil", agora - timedelta(hours=1))
    # mec: último sucesso há 20 dias (fora dos 7) e html_changed desde então.
    _execucao("mec", agora - timedelta(days=20))
    _execucao("mec", agora - timedelta(days=2), "error", "html_changed", "antiga")
    _execucao("mec", agora - timedelta(minutes=30), "error", "html_changed", "x" * 600)
    # antaq: nunca teve sucesso.
    _execucao("antaq", agora - timedelta(hours=2), "error", "access_denied", "HTTP 403")
    for chave in ("saude", "gestao", "ibama"):
        _execucao(chave, agora - timedelta(hours=2))
    # ansn: ativa no scraper, fora de agencies (sem FK) e sem notícias.
    _execucao("ansn", agora - timedelta(hours=2))
    # sudam: só execuções antigas.
    _execucao("sudam", agora - timedelta(days=10))
    return agora


def _estado() -> dict[str, dict]:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scrape_agency_state")
            return {row["agency_key"]: dict(row) for row in cur.fetchall()}
    finally:
        conn.close()


def _nos_do_plano(no: dict):
    yield no
    for filho in no.get("Plans", []):
        yield from _nos_do_plano(filho)


@pytest.mark.integration
class TestScrapeAgencyStateMigration:
    """038: scrape_agency_state e scrape_dispatch_meta, com o seed (Passo 2 da rearquitetura).

    Estado por agência da ingestão (faixa, próxima raspagem, marca d'água, disjuntor), escrito
    pelo scraper-api na transação de scrape_runs. Sem FK para agencies.
    """

    def test_038_nao_e_tratada_como_migracao_concorrente(self):
        """A palavra do CREATE INDEX não transacional faria o teste stampar 013–037 sem rodar."""
        assert "038" not in CONCURRENT_MIGRATIONS

    def test_038_cria_scrape_agency_state_com_o_contrato(self):
        _apply_all_migrations()

        assert _columns("scrape_agency_state") == _SCRAPE_AGENCY_STATE_CONTRATO

    def test_038_cria_scrape_dispatch_meta_com_o_contrato(self):
        _apply_all_migrations()

        assert _columns("scrape_dispatch_meta") == {
            "key": ("text", "NO"),
            "value": ("jsonb", "NO"),
            "updated_at": (_TSTZ, "NO"),
        }

    def test_038_defaults_de_uma_agencia_nova(self):
        """O ensure_rows do scraper insere só a chave: h2/120, vencida agora, circuito fechado."""
        _apply_all_migrations()
        _execute("INSERT INTO scrape_agency_state (agency_key) VALUES ('mec')")
        _execute("INSERT INTO scrape_dispatch_meta (key) VALUES ('tiers_recomputed_on')")

        row = _estado()["mec"]
        assert (row["tier"], row["poll_interval_minutes"], row["circuit_state"]) == (
            "h2",
            120,
            "closed",
        )
        assert row["consecutive_permanent_failures"] == 0
        assert row["consecutive_transient_failures"] == 0
        assert row["circuit_failed_probes"] == 0
        assert row["next_due_at"] == row["created_at"] == row["updated_at"]
        assert row["rate_ewma_per_day"] is None
        assert row["last_success_at"] is None
        assert _execute("SELECT value FROM scrape_dispatch_meta") == [({},)]

    @pytest.mark.parametrize(
        "coluna_valor",
        ["tier = 'h1'", "circuit_state = 'aberto'", "poll_interval_minutes = 0"],
    )
    def test_038_checks_de_faixa_intervalo_e_circuito(self, coluna_valor):
        _apply_all_migrations()
        _execute("INSERT INTO scrape_agency_state (agency_key) VALUES ('mec')")

        with pytest.raises(psycopg2.errors.CheckViolation):
            _execute(f"UPDATE scrape_agency_state SET {coluna_valor} WHERE agency_key = 'mec'")

    def test_038_indice_de_vencimento_e_sem_fk(self):
        """O /dispatch busca por next_due_at; ansn e povosindigenas não estão em agencies."""
        _apply_all_migrations()

        assert _indexes("scrape_agency_state")["idx_scrape_agency_state_next_due"].endswith(
            "USING btree (next_due_at)"
        )
        fks = _execute(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE constraint_type = 'FOREIGN KEY' "
            "AND table_name IN ('scrape_agency_state', 'scrape_dispatch_meta')"
        )
        assert fks == [(0,)]
        _execute("INSERT INTO scrape_agency_state (agency_key) VALUES ('povosindigenas')")

    def test_038_comenta_tabela_e_formula_da_taxa(self):
        _apply_all_migrations()

        tabela = _execute("SELECT obj_description('scrape_agency_state'::regclass, 'pg_class')")
        assert "scrape_runs" in tabela[0][0]
        taxa = _execute(
            "SELECT col_description('scrape_agency_state'::regclass, attnum) FROM pg_attribute "
            "WHERE attrelid = 'scrape_agency_state'::regclass AND attname = 'rate_ewma_per_day'"
        )
        assert "meia-vida de 7 dias" in taxa[0][0]
        assert "0.5 ^ (idade_d / 7)" in taxa[0][0]

    def test_038_seed_uma_linha_por_agencia_com_execucao_em_7_dias(self):
        """sudam (só execução de 10 dias atrás) e planalto (só notícias) ficam de fora."""
        _cenario_do_seed()

        _apply_all_migrations()

        assert set(_estado()) == _SEMEADAS

    def test_038_seed_taxa_ewma_e_faixa(self):
        """EWMA de 28 dias BRT por published_at: hoje e o 29º dia ficam fora; 0 sem notícia."""
        _cenario_do_seed()

        _apply_all_migrations()

        estado = _estado()
        esperadas = {
            "agencia_brasil": 10.0,
            "saude": 2.0,
            "gestao": _ewma_esperada({0: 3}),
            "ibama": _ewma_esperada(_IBAMA_POR_IDADE),
            "mec": 0.0,
            "antaq": 0.0,
            "ansn": 0.0,
        }
        for chave, taxa in esperadas.items():
            row = estado[chave]
            assert row["rate_ewma_per_day"] == pytest.approx(taxa, rel=1e-9, abs=1e-12), chave
            assert (row["tier"], row["poll_interval_minutes"]) == _faixa(taxa), chave
        # Uma agência por faixa no cenário.
        assert {estado[c]["tier"] for c in ("agencia_brasil", "saude", "gestao", "mec")} == {
            "m30",
            "h2",
            "h6",
            "d1",
        }
        assert estado["ibama"]["tier"] == "h6"

    def test_038_seed_marca_dagua_e_ultimo_erro(self):
        agora = _cenario_do_seed()

        _apply_all_migrations()

        estado = _estado()
        ab = estado["agencia_brasil"]
        assert ab["last_attempt_at"] == ab["last_success_at"] == agora - timedelta(hours=1)
        assert (ab["last_error_category"], ab["last_error_message"]) == (None, None)

        # Marca d'água real, mesmo fora dos 7 dias: a janela do scraper limita a 7.
        mec = estado["mec"]
        assert mec["last_attempt_at"] == agora - timedelta(minutes=30)
        assert mec["last_success_at"] == agora - timedelta(days=20)
        assert mec["last_error_category"] == "html_changed"
        assert mec["last_error_message"] == "x" * 500

        antaq = estado["antaq"]
        assert antaq["last_success_at"] is None
        assert (antaq["last_error_category"], antaq["last_error_message"]) == (
            "access_denied",
            "HTTP 403",
        )

    def test_038_seed_comeca_com_circuito_fechado_e_vencido(self):
        agora = _cenario_do_seed()

        _apply_all_migrations()

        for chave, row in _estado().items():
            assert row["circuit_state"] == "closed", chave
            assert (
                row["consecutive_permanent_failures"],
                row["consecutive_transient_failures"],
                row["circuit_failed_probes"],
            ) == (0, 0, 0), chave
            for coluna in (
                "boost_until",
                "last_dispatched_at",
                "last_new_article_at",
                "failure_streak_started_at",
                "circuit_opened_at",
            ):
                assert row[coluna] is None, (chave, coluna)
            assert row["tier_updated_at"] == row["next_due_at"] == row["created_at"], chave
            assert abs(row["next_due_at"] - agora) < timedelta(minutes=5), chave

    def test_038_seed_usa_o_dia_de_brasilia_em_qualquer_timezone_da_sessao(self):
        _cenario_do_seed()

        _execute("SET TIME ZONE 'Asia/Tokyo'; " + _MIGRATION_038.read_text())

        estado = _estado()
        assert set(estado) == _SEMEADAS
        assert estado["agencia_brasil"]["rate_ewma_per_day"] == pytest.approx(10.0)
        assert estado["gestao"]["rate_ewma_per_day"] == pytest.approx(_ewma_esperada({0: 3}))
        assert estado["ibama"]["rate_ewma_per_day"] == pytest.approx(
            _ewma_esperada(_IBAMA_POR_IDADE)
        )

    def test_038_seed_idempotente_nao_sobrescreve_o_estado(self):
        """Reaplicar só acrescenta agências novas; o estado gravado pelo scraper fica."""
        _cenario_do_seed()
        _apply_all_migrations()
        _execute(
            "UPDATE scrape_agency_state SET circuit_state = 'open', "
            "consecutive_permanent_failures = 2 WHERE agency_key = 'mec'"
        )
        _execute("UPDATE scrape_agency_state SET tier = 'm30' WHERE agency_key = 'saude'")
        _execucao("nova", datetime.now(UTC))

        _execute(_MIGRATION_038.read_text())

        estado = _estado()
        assert set(estado) == _SEMEADAS | {"nova"}
        assert (
            estado["mec"]["circuit_state"],
            estado["mec"]["consecutive_permanent_failures"],
        ) == (
            "open",
            2,
        )
        assert estado["saude"]["tier"] == "m30"
        assert estado["nova"]["tier"] == "d1"

    def test_038_rollback_remove_as_tabelas_e_reaplica_o_seed(self):
        _cenario_do_seed()
        _apply_all_migrations()
        runs = _execute("SELECT count(*) FROM scrape_runs")
        noticias = _execute("SELECT count(*) FROM news")

        result = _run_migrate("rollback", "038", "--yes")
        assert result.returncode == 0, f"Rollback failed:\n{result.stdout}\n{result.stderr}"
        assert _columns("scrape_agency_state") == {}
        assert _columns("scrape_dispatch_meta") == {}
        assert _execute("SELECT count(*) FROM scrape_runs") == runs
        assert _execute("SELECT count(*) FROM news") == noticias

        result = _run_migrate("migrate", "--yes")
        assert result.returncode == 0, f"Re-apply failed:\n{result.stdout}\n{result.stderr}"
        assert set(_estado()) == _SEMEADAS

    def test_038_seed_le_news_pelo_indice_de_published_at(self):
        """A taxa lê só a faixa de 28 dias de published_at, não a tabela inteira."""
        _apply_all_migrations()
        _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")
        # ~3 anos de notícias (100 mil, uma a cada 15 min) em 50 agências: 28 dias são ~2,7%.
        _execute(
            "INSERT INTO news (unique_id, agency_id, agency_key, title, published_at) "
            "SELECT 'n' || g, a.id, 'ag' || (g % 50), 'Título', NOW() - g * INTERVAL '15 minutes' "
            "FROM agencies AS a CROSS JOIN generate_series(1, 100000) AS g WHERE a.key = 'mec'"
        )
        _execute(
            "INSERT INTO scrape_runs (agency_key, status) "
            "SELECT 'ag' || g, 'success' FROM generate_series(0, 49) AS g"
        )
        _execute("ANALYZE news; ANALYZE scrape_runs")
        seed = re.search(
            r"^WITH janela AS .*?ON CONFLICT \(agency_key\) DO NOTHING;",
            _MIGRATION_038.read_text(),
            re.S | re.M,
        ).group(0)

        plano = _execute("EXPLAIN (FORMAT JSON) " + seed)[0][0][0]["Plan"]

        nos = list(_nos_do_plano(plano))
        leituras_de_news = [n for n in nos if n.get("Relation Name") == "news"]
        assert leituras_de_news
        assert all(n["Node Type"] != "Seq Scan" for n in leituras_de_news)
        assert "idx_news_published_at" in {n.get("Index Name") for n in nos}

    def test_038_nao_espera_o_insert_do_scraper(self):
        """O seed só lê scrape_runs e news: um INSERT do scraper em andamento não o bloqueia."""
        result = _run_migrate("migrate", "--target", "037", "--yes")
        assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"
        _execute("INSERT INTO agencies (key, name) VALUES ('mec', 'MEC')")

        scraper = psycopg2.connect(DATABASE_URL)
        try:
            with scraper.cursor() as cur:
                cur.execute(
                    "INSERT INTO scrape_runs (agency_key, status) VALUES ('mec', 'success')"
                )
                cur.execute(
                    "INSERT INTO news (unique_id, agency_id, agency_key, title, published_at) "
                    "SELECT 'em-andamento', id, 'mec', 'Título', NOW() FROM agencies"
                )
            try:
                result = _run_migrate("migrate", "--target", "038", "--yes", timeout=60)
            except subprocess.TimeoutExpired:
                pytest.fail("a 038 esperou o INSERT do scraper")
        finally:
            scraper.rollback()
            scraper.close()

        assert result.returncode == 0, f"Migrate failed:\n{result.stdout}\n{result.stderr}"
        assert _estado() == {}

    @pytest.mark.parametrize(
        ("comando", "aplicada_antes", "trava"),
        [
            (
                ("migrate", "--target", "038"),
                False,
                "LOCK TABLE scrape_runs IN ACCESS EXCLUSIVE MODE",
            ),
            (("rollback", "038"), True, "SELECT count(*) FROM scrape_agency_state"),
        ],
        ids=["migrate", "rollback"],
    )
    def test_038_desiste_do_lock_em_vez_de_enfileirar(self, comando, aplicada_antes, trava):
        """lock_timeout: atrás de uma transação que segura a tabela, a 038 falha inteira.

        migrate: outra migração com ACCESS EXCLUSIVE em scrape_runs. rollback: o scraper lendo
        o estado (ACCESS SHARE) bloqueia o DROP TABLE, que enfileiraria todo record_scrape_run.
        """
        if aplicada_antes:
            _apply_all_migrations()
        else:
            result = _run_migrate("migrate", "--target", "037", "--yes")
            assert result.returncode == 0, f"Setup failed:\n{result.stdout}\n{result.stderr}"

        outra = psycopg2.connect(DATABASE_URL)
        try:
            with outra.cursor() as cur:
                cur.execute(trava)
            inicio = time.monotonic()
            try:
                result = _run_migrate(*comando, "--yes", timeout=60)
            except subprocess.TimeoutExpired:
                pytest.fail(f"`{' '.join(comando)}` esperou o lock sem prazo (sem lock_timeout)")
            espera = time.monotonic() - inicio
        finally:
            outra.rollback()
            outra.close()

        assert result.returncode != 0
        assert "lock timeout" in result.stdout + result.stderr
        assert espera < 45
        assert bool(_columns("scrape_agency_state")) is aplicada_antes

        result = _run_migrate(*comando, "--yes")
        assert result.returncode == 0, f"Retry failed:\n{result.stdout}\n{result.stderr}"
        assert bool(_columns("scrape_agency_state")) is not aplicada_antes


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
