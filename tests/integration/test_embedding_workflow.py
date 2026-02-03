"""
Integration tests for the complete embedding workflow.

Tests the end-to-end flow:
1. Generate embeddings for test news records (using mocked Embeddings API)
2. Sync embeddings to Typesense (using mocked Typesense client)
3. Validate data flows correctly through the entire pipeline

This is an INTEGRATION test - it uses real PostgreSQL (test database)
but mocks external services (Typesense, Embeddings API).

Run with: pytest tests/integration/test_embedding_workflow.py -v
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from pytest_postgresql import factories

from data_platform.jobs.embeddings.embedding_generator import EmbeddingGenerator
from data_platform.jobs.typesense.sync_job import sync_to_typesense

# pytest-postgresql configuration
# This creates a temporary PostgreSQL instance for testing
postgresql_proc = factories.postgresql_proc(
    port=None,  # Random available port
    unixsocketdir="/tmp",
)

postgresql = factories.postgresql("postgresql_proc")


@pytest.fixture  # type: ignore[untyped-decorator]
def test_database_url(postgresql_proc: Any) -> str:
    """Generate database URL from postgresql process."""
    return (
        f"postgresql://{postgresql_proc.user}@{postgresql_proc.host}:"
        f"{postgresql_proc.port}/{postgresql_proc.dbname}"
    )


@pytest.fixture  # type: ignore[untyped-decorator]
def mock_api_url() -> str:
    """Mock embeddings API URL."""
    return "https://embeddings-api.example.com"


@pytest.fixture  # type: ignore[untyped-decorator]
def mock_api_key() -> str:
    """Mock API key."""
    return "test-api-key-12345"


@pytest.fixture  # type: ignore[untyped-decorator]
def setup_test_schema(postgresql: Any) -> bool:
    """
    Set up the test database schema.

    Creates:
    - agencies table with sample data
    - themes table with sample data
    - news table with pgvector extension
    - sync_log table
    """
    cur = postgresql.cursor()

    # Enable pgvector extension (if available, otherwise skip vector tests)
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        postgresql.commit()
        has_vector = True
    except Exception:
        # pgvector not available - we'll work around it
        postgresql.rollback()
        has_vector = False

    # Create agencies table
    cur.execute("""
        CREATE TABLE agencies (
            id SERIAL PRIMARY KEY,
            key VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(500) NOT NULL,
            type VARCHAR(100),
            parent_key VARCHAR(100),
            url VARCHAR(1000),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # Insert sample agencies
    cur.execute("""
        INSERT INTO agencies (key, name, type) VALUES
        ('mec', 'Ministério da Educação', 'Ministério'),
        ('saude', 'Ministério da Saúde', 'Ministério'),
        ('fazenda', 'Ministério da Fazenda', 'Ministério');
    """)

    # Create themes table
    cur.execute("""
        CREATE TABLE themes (
            id SERIAL PRIMARY KEY,
            code VARCHAR(20) UNIQUE NOT NULL,
            label VARCHAR(500) NOT NULL,
            full_name VARCHAR(600),
            level SMALLINT NOT NULL CHECK (level IN (1, 2, 3)),
            parent_code VARCHAR(20),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    # Insert sample themes (3 levels)
    cur.execute("""
        INSERT INTO themes (code, label, full_name, level, parent_code) VALUES
        -- Level 1
        ('01', 'Educação', '01 - Educação', 1, NULL),
        ('02', 'Saúde', '02 - Saúde', 1, NULL),
        -- Level 2
        ('01.01', 'Ensino Superior', '01.01 - Ensino Superior', 2, '01'),
        ('02.01', 'Política de Saúde', '02.01 - Política de Saúde', 2, '02'),
        -- Level 3
        ('01.01.01', 'Universidades', '01.01.01 - Universidades', 3, '01.01'),
        ('02.01.01', 'SUS', '02.01.01 - SUS', 3, '02.01');
    """)

    # Create news table
    if has_vector:
        cur.execute("""
            CREATE TABLE news (
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
                content TEXT,
                summary TEXT,
                subtitle TEXT,
                editorial_lead TEXT,
                published_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_datetime TIMESTAMP WITH TIME ZONE,
                extracted_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                synced_to_hf_at TIMESTAMP WITH TIME ZONE,
                agency_key VARCHAR(100),
                agency_name VARCHAR(500),
                content_embedding vector(768),
                embedding_generated_at TIMESTAMP WITH TIME ZONE,
                theme_l1_code VARCHAR(20),
                theme_l1_label VARCHAR(500),
                theme_l2_code VARCHAR(20),
                theme_l2_label VARCHAR(500),
                theme_l3_code VARCHAR(20),
                theme_l3_label VARCHAR(500),
                most_specific_theme_code VARCHAR(20),
                most_specific_theme_label VARCHAR(500),
                tags TEXT[]
            );
        """)
    else:
        # Fallback: use FLOAT[] instead of vector
        cur.execute("""
            CREATE TABLE news (
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
                content TEXT,
                summary TEXT,
                subtitle TEXT,
                editorial_lead TEXT,
                published_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_datetime TIMESTAMP WITH TIME ZONE,
                extracted_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                synced_to_hf_at TIMESTAMP WITH TIME ZONE,
                agency_key VARCHAR(100),
                agency_name VARCHAR(500),
                content_embedding FLOAT[],
                embedding_generated_at TIMESTAMP WITH TIME ZONE,
                theme_l1_code VARCHAR(20),
                theme_l1_label VARCHAR(500),
                theme_l2_code VARCHAR(20),
                theme_l2_label VARCHAR(500),
                theme_l3_code VARCHAR(20),
                theme_l3_label VARCHAR(500),
                most_specific_theme_code VARCHAR(20),
                most_specific_theme_label VARCHAR(500),
                tags TEXT[]
            );
        """)

    # Create sync_log table
    cur.execute("""
        CREATE TABLE sync_log (
            id SERIAL PRIMARY KEY,
            operation VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            records_processed INTEGER DEFAULT 0,
            records_failed INTEGER DEFAULT 0,
            started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            completed_at TIMESTAMP WITH TIME ZONE,
            error_message TEXT,
            metadata JSONB
        );
    """)

    postgresql.commit()

    return has_vector


@pytest.fixture  # type: ignore[untyped-decorator]
def sample_2025_news(postgresql: Any, setup_test_schema: bool) -> list[str]:
    """
    Insert sample news data from 2025 (the target year for embeddings).

    Returns the IDs of inserted records.
    """
    cur = postgresql.cursor()

    # Get agency IDs
    cur.execute("SELECT id FROM agencies WHERE key = 'mec'")
    mec_id = cur.fetchone()[0]

    cur.execute("SELECT id FROM agencies WHERE key = 'saude'")
    saude_id = cur.fetchone()[0]

    # Get theme IDs
    cur.execute("SELECT id FROM themes WHERE code = '01'")
    theme_l1_id = cur.fetchone()[0]

    cur.execute("SELECT id FROM themes WHERE code = '01.01'")
    theme_l2_id = cur.fetchone()[0]

    cur.execute("SELECT id FROM themes WHERE code = '01.01.01'")
    theme_l3_id = cur.fetchone()[0]

    # Insert 10 news records from 2025
    news_data = [
        {
            "unique_id": f"test_2025_{i:03d}",
            "agency_id": mec_id if i % 2 == 0 else saude_id,
            "agency_key": "mec" if i % 2 == 0 else "saude",
            "agency_name": "Ministério da Educação" if i % 2 == 0 else "Ministério da Saúde",
            "theme_l1_id": theme_l1_id,
            "theme_l2_id": theme_l2_id,
            "theme_l3_id": theme_l3_id,
            "theme_l1_code": "01",
            "theme_l1_label": "Educação",
            "theme_l2_code": "01.01",
            "theme_l2_label": "Ensino Superior",
            "theme_l3_code": "01.01.01",
            "theme_l3_label": "Universidades",
            "most_specific_theme_id": theme_l3_id,
            "most_specific_theme_code": "01.01.01",
            "most_specific_theme_label": "Universidades",
            "title": f"Notícia de teste {i + 1} sobre educação em 2025",
            "url": f"https://www.gov.br/mec/noticias/2025/test-{i}",
            "content": f"Conteúdo completo da notícia {i + 1}. Esta é uma notícia de teste sobre políticas educacionais no Brasil.",
            "summary": f"Resumo da notícia {i + 1} gerado por IA. Aborda temas educacionais importantes.",
            "published_at": f"2025-01-{(i % 28) + 1:02d} 10:00:00+00",
            "extracted_at": f"2025-01-{(i % 28) + 1:02d} 11:00:00+00",
        }
        for i in range(10)
    ]

    # Also insert 3 news from 2024 (these should NOT be processed)
    news_data_2024 = [
        {
            "unique_id": f"test_2024_{i:03d}",
            "agency_id": mec_id,
            "agency_key": "mec",
            "agency_name": "Ministério da Educação",
            "theme_l1_id": None,
            "theme_l2_id": None,
            "theme_l3_id": None,
            "most_specific_theme_id": None,
            "theme_l1_code": None,
            "theme_l1_label": None,
            "theme_l2_code": None,
            "theme_l2_label": None,
            "theme_l3_code": None,
            "theme_l3_label": None,
            "most_specific_theme_code": None,
            "most_specific_theme_label": None,
            "title": f"Notícia antiga {i + 1} de 2024",
            "url": f"https://www.gov.br/mec/noticias/2024/test-{i}",
            "content": f"Conteúdo da notícia antiga {i + 1}.",
            "summary": None,
            "published_at": f"2024-12-{25 + i:02d} 10:00:00+00",
            "extracted_at": f"2024-12-{25 + i:02d} 11:00:00+00",
        }
        for i in range(3)
    ]

    all_news = news_data + news_data_2024

    for news in all_news:
        cur.execute(
            """
            INSERT INTO news (
                unique_id, agency_id, agency_key, agency_name,
                theme_l1_id, theme_l2_id, theme_l3_id, most_specific_theme_id,
                theme_l1_code, theme_l1_label,
                theme_l2_code, theme_l2_label,
                theme_l3_code, theme_l3_label,
                most_specific_theme_code, most_specific_theme_label,
                title, url, content, summary, published_at, extracted_at
            ) VALUES (
                %(unique_id)s, %(agency_id)s, %(agency_key)s, %(agency_name)s,
                %(theme_l1_id)s, %(theme_l2_id)s, %(theme_l3_id)s, %(most_specific_theme_id)s,
                %(theme_l1_code)s, %(theme_l1_label)s,
                %(theme_l2_code)s, %(theme_l2_label)s,
                %(theme_l3_code)s, %(theme_l3_label)s,
                %(most_specific_theme_code)s, %(most_specific_theme_label)s,
                %(title)s, %(url)s, %(content)s, %(summary)s, %(published_at)s, %(extracted_at)s
            )
            """,
            news,
        )

    postgresql.commit()

    # Return the unique_ids of 2025 news
    return [news["unique_id"] for news in news_data]


@pytest.fixture  # type: ignore[untyped-decorator]
def mock_embeddings_api() -> MagicMock:
    """
    Mock the Embeddings API to avoid requiring a real Cloud Run service.

    Returns a mock httpx client that simulates the embeddings API.
    """

    def create_mock_response(texts: list[str]) -> dict[str, Any]:
        """Generate mock API response with fake embeddings."""
        embeddings = np.random.randn(len(texts), 768).astype(np.float32)
        # Normalize
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / norms

        return {
            "embeddings": embeddings.tolist(),
            "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            "dimension": 768,
            "count": len(texts),
        }

    mock_client = MagicMock()

    def mock_post(
        url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> MagicMock:
        """Mock POST request to embeddings API."""
        mock_response = MagicMock()
        if "/generate" in url and json:
            texts = json.get("texts", [])
            mock_response.json.return_value = create_mock_response(texts)
        else:
            mock_response.json.return_value = {"error": "Not found"}
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)
    mock_client.post = mock_post

    return mock_client


class TestEmbeddingWorkflow:
    """Integration tests for the complete embedding workflow."""

    def test_embedding_generator_initialization(
        self, test_database_url: str, mock_api_url: str, mock_api_key: str
    ) -> None:
        """Test that EmbeddingGenerator can be initialized with test database."""
        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )
        assert generator.database_url == test_database_url
        assert generator.api_url == mock_api_url

    def test_fetch_news_without_embeddings_only_2025(
        self,
        test_database_url: str,
        sample_2025_news: list[str],
        mock_api_url: str,
        mock_api_key: str,
    ) -> None:
        """
        Test that only 2025 news are fetched for embedding generation.

        This validates the key requirement: only 2025 news should be processed.
        """
        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        # Fetch news without embeddings from 2025-01-01 to 2025-01-31
        news_records = generator._fetch_news_without_embeddings(
            start_date="2025-01-01", end_date="2025-01-31"
        )

        # Should get all 10 news from 2025
        assert len(news_records) == 10

        # Verify all records have expected format (id, title, summary, content)
        for record in news_records:
            assert len(record) == 4
            assert isinstance(record[0], int)  # ID
            assert isinstance(record[1], str)  # Title

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_success(
        self,
        mock_client_class: MagicMock,
        test_database_url: str,
        sample_2025_news: list[str],
        mock_embeddings_api: MagicMock,
        mock_api_url: str,
        mock_api_key: str,
        postgresql: Any,
    ) -> None:
        """
        Test the complete embedding generation workflow.

        This validates:
        1. Embeddings are generated for all 2025 news
        2. Embeddings are stored in PostgreSQL
        3. embedding_generated_at timestamp is set
        """
        mock_client_class.return_value = mock_embeddings_api

        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        # Generate embeddings for January 2025
        result = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-31", batch_size=5
        )

        # Verify statistics
        assert result["processed"] == 10
        assert result["successful"] == 10
        assert result["failed"] == 0

        # Verify embeddings were stored in database
        cur = postgresql.cursor()
        cur.execute("""
            SELECT COUNT(*)
            FROM news
            WHERE content_embedding IS NOT NULL
              AND published_at >= '2025-01-01'
        """)
        count_with_embeddings = cur.fetchone()[0]
        assert count_with_embeddings == 10

        # Verify embedding_generated_at is set
        cur.execute("""
            SELECT COUNT(*)
            FROM news
            WHERE embedding_generated_at IS NOT NULL
              AND published_at >= '2025-01-01'
        """)
        count_with_timestamp = cur.fetchone()[0]
        assert count_with_timestamp == 10

        # Verify 2024 news were NOT processed
        cur.execute("""
            SELECT COUNT(*)
            FROM news
            WHERE content_embedding IS NOT NULL
              AND published_at < '2025-01-01'
        """)
        count_2024_with_embeddings = cur.fetchone()[0]
        assert count_2024_with_embeddings == 0

    def test_embedding_text_preparation(
        self, test_database_url: str, mock_api_url: str, mock_api_key: str
    ) -> None:
        """
        Test the text preparation strategy for embeddings.

        Validates: title + " " + summary (fallback to content if summary missing)
        """
        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        # Test with summary
        text1 = generator._prepare_text_for_embedding(
            title="Test Title", summary="Test Summary", content="Test Content"
        )
        assert text1 == "Test Title Test Summary"

        # Test without summary (fallback to content)
        text2 = generator._prepare_text_for_embedding(
            title="Test Title", summary=None, content="Test Content Here"
        )
        assert text2 == "Test Title Test Content Here"

        # Test with empty summary (fallback to content)
        text3 = generator._prepare_text_for_embedding(
            title="Test Title", summary="   ", content="Test Content"
        )
        assert text3 == "Test Title Test Content"

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_fetch_news_with_embeddings(
        self,
        mock_client_class: MagicMock,
        test_database_url: str,
        sample_2025_news: list[str],
        mock_embeddings_api: MagicMock,
        mock_api_url: str,
        mock_api_key: str,
        postgresql: Any,
    ) -> None:
        """
        Test fetching news that have embeddings for Typesense sync.
        """
        # First generate embeddings
        mock_client_class.return_value = mock_embeddings_api

        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )
        generator.generate_embeddings(start_date="2025-01-01", end_date="2025-01-31")

        # Now fetch using PostgresManager directly
        from data_platform.managers.postgres_manager import PostgresManager

        pg_manager = PostgresManager(connection_string=test_database_url)
        try:
            # Fetch news with embeddings
            df = pg_manager.get_news_for_typesense(start_date="2025-01-01", end_date="2025-01-31")

            # Should get all 10 news with embeddings
            assert len(df) == 10

            # Verify all have embeddings
            assert "content_embedding" in df.columns
            assert df["content_embedding"].notna().all()
        finally:
            pg_manager.close_all()  # type: ignore[no-untyped-call]

    @patch("data_platform.jobs.typesense.sync_job.index_documents")
    @patch("data_platform.jobs.typesense.sync_job.create_collection")
    @patch("data_platform.jobs.typesense.sync_job.get_client")
    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    @patch("data_platform.jobs.typesense.sync_job.PostgresManager")
    def test_complete_workflow_generate_and_sync(
        self,
        mock_pg_manager_class: MagicMock,
        mock_http_client_class: MagicMock,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        test_database_url: str,
        sample_2025_news: list[str],
        mock_embeddings_api: MagicMock,
        mock_api_url: str,
        mock_api_key: str,
        postgresql: Any,
    ) -> None:
        """
        MAIN INTEGRATION TEST: Test the complete workflow.

        This test validates:
        1. Generate embeddings for 2025 news
        2. Sync those embeddings to Typesense
        3. Verify data flows correctly through the entire pipeline
        """
        # Step 1: Generate embeddings
        mock_http_client_class.return_value = mock_embeddings_api

        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        gen_result = generator.generate_embeddings(
            start_date="2025-01-01", end_date="2025-01-31", batch_size=5
        )

        # Verify generation succeeded
        assert gen_result["successful"] == 10
        assert gen_result["failed"] == 0

        # Step 2: Sync to Typesense
        # Setup PostgresManager mock
        mock_pg_manager = MagicMock()
        mock_pg_manager_class.return_value = mock_pg_manager

        # Mock get_news_for_typesense to return test data
        from data_platform.managers.postgres_manager import PostgresManager

        real_pg_manager = PostgresManager(connection_string=test_database_url)
        mock_pg_manager.get_news_for_typesense.return_value = (
            real_pg_manager.get_news_for_typesense(
                start_date="2025-01-01", end_date="2025-01-31", limit=100
            )
        )
        real_pg_manager.close_all()  # type: ignore[no-untyped-call]

        # Setup Typesense mocks
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        # Mock index_documents to return success
        mock_index_documents.return_value = {
            "total_processed": 10,
            "total_indexed": 10,
            "errors": 0,
            "skipped": False,
        }

        # Call sync_to_typesense function
        sync_result = sync_to_typesense(
            start_date="2025-01-01", end_date="2025-01-31", batch_size=5, limit=100
        )

        # Verify sync succeeded
        assert sync_result["total_indexed"] == 10
        assert sync_result["errors"] == 0
        assert sync_result["total_fetched"] == 10

        # Step 3: Verify data in PostgreSQL
        cur = postgresql.cursor()

        # All 2025 news should have embeddings
        cur.execute("""
            SELECT COUNT(*)
            FROM news
            WHERE published_at >= '2025-01-01'
              AND content_embedding IS NOT NULL
              AND embedding_generated_at IS NOT NULL
        """)
        count = cur.fetchone()[0]
        assert count == 10

        # No 2024 news should have embeddings
        cur.execute("""
            SELECT COUNT(*)
            FROM news
            WHERE published_at < '2025-01-01'
              AND content_embedding IS NOT NULL
        """)
        count_2024 = cur.fetchone()[0]
        assert count_2024 == 0

        # Verify embedding dimensions (should be list/array of 768 floats)
        cur.execute("""
            SELECT content_embedding
            FROM news
            WHERE published_at >= '2025-01-01'
            LIMIT 1
        """)
        embedding = cur.fetchone()[0]

        # Convert to list if needed (depends on pgvector vs FLOAT[])
        if isinstance(embedding, str):
            embedding_list = json.loads(embedding)
        elif isinstance(embedding, list):
            embedding_list = embedding
        else:
            # Might be pgvector binary format or array
            embedding_list = list(embedding)

        assert len(embedding_list) == 768
        assert all(isinstance(x, (int, float)) for x in embedding_list)


class TestEmbeddingWorkflowEdgeCases:
    """Test edge cases and error scenarios."""

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_generate_embeddings_no_records(
        self,
        mock_client_class: MagicMock,
        test_database_url: str,
        setup_test_schema: bool,
        mock_embeddings_api: MagicMock,
        mock_api_url: str,
        mock_api_key: str,
    ) -> None:
        """Test generating embeddings when no records need processing."""
        mock_client_class.return_value = mock_embeddings_api

        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        # Try to generate for a date range with no data
        result = generator.generate_embeddings(start_date="2025-12-01", end_date="2025-12-31")

        assert result["processed"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0

    @patch("data_platform.jobs.typesense.sync_job.PostgresManager")
    @patch("data_platform.jobs.typesense.sync_job.index_documents")
    @patch("data_platform.jobs.typesense.sync_job.create_collection")
    @patch("data_platform.jobs.typesense.sync_job.get_client")
    def test_sync_no_embeddings(
        self,
        mock_get_client: MagicMock,
        mock_create_collection: MagicMock,
        mock_index_documents: MagicMock,
        mock_pg_manager_class: MagicMock,
        test_database_url: str,
    ) -> None:
        """Test syncing when no embeddings exist."""
        # Setup PostgresManager mock
        mock_pg_manager = MagicMock()
        mock_pg_manager_class.return_value = mock_pg_manager

        # Mock get_news_for_typesense to return empty dataframe
        import pandas as pd

        mock_pg_manager.get_news_for_typesense.return_value = pd.DataFrame()

        # Setup Typesense mocks
        mock_ts_client = MagicMock()
        mock_get_client.return_value = mock_ts_client

        # Call sync_to_typesense for a date range with no data
        result = sync_to_typesense(start_date="2025-12-01", end_date="2025-12-31", limit=100)

        # Should return 0 records processed
        assert result["total_fetched"] == 0
        assert result["total_indexed"] == 0

        # index_documents should not be called
        mock_index_documents.assert_not_called()

    @patch("data_platform.jobs.embeddings.embedding_generator.httpx.Client")
    def test_embedding_with_missing_summary(
        self,
        mock_client_class: MagicMock,
        test_database_url: str,
        sample_2025_news: list[str],
        mock_embeddings_api: MagicMock,
        mock_api_url: str,
        mock_api_key: str,
        postgresql: Any,
    ) -> None:
        """
        Test embedding generation when summary is missing (fallback to content).
        """
        # Remove summaries from some records
        cur = postgresql.cursor()
        cur.execute("""
            UPDATE news
            SET summary = NULL
            WHERE unique_id LIKE 'test_2025_00%'
        """)
        postgresql.commit()

        mock_client_class.return_value = mock_embeddings_api

        generator = EmbeddingGenerator(
            database_url=test_database_url,
            api_url=mock_api_url,
            api_key=mock_api_key,
        )

        # Should still succeed (fallback to content)
        result = generator.generate_embeddings(start_date="2025-01-01", end_date="2025-01-31")

        assert result["successful"] == 10
        assert result["failed"] == 0
