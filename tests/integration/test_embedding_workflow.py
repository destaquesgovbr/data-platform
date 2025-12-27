"""
Integration tests for the complete embedding workflow.

Tests the end-to-end flow:
1. Generate embeddings for test news records (using mocked ML model)
2. Sync embeddings to Typesense (using mocked Typesense client)
3. Validate data flows correctly through the entire pipeline

This is an INTEGRATION test - it uses real PostgreSQL (test database)
but mocks external services (Typesense, ML model).

Run with: pytest tests/integration/test_embedding_workflow.py -v
"""

import json
import struct
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest
from pytest_postgresql import factories

from data_platform.jobs.embeddings.embedding_generator import EmbeddingGenerator
from data_platform.jobs.embeddings.typesense_sync import TypesenseSyncManager

# pytest-postgresql configuration
# This creates a temporary PostgreSQL instance for testing
postgresql_proc = factories.postgresql_proc(
    port=None,  # Random available port
    unixsocketdir="/tmp",
)

postgresql = factories.postgresql("postgresql_proc")


@pytest.fixture(scope="module")
def test_database_url(postgresql_proc):
    """Generate database URL from postgresql process."""
    return (
        f"postgresql://{postgresql_proc.user}@{postgresql_proc.host}:"
        f"{postgresql_proc.port}/{postgresql_proc.dbname}"
    )


@pytest.fixture(scope="module")
def setup_test_schema(postgresql):
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
        has_vector = True
    except Exception:
        # pgvector not available - we'll work around it
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
                most_specific_theme_label VARCHAR(500)
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
                most_specific_theme_label VARCHAR(500)
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


@pytest.fixture
def sample_2025_news(postgresql, setup_test_schema):
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
            'unique_id': f'test_2025_{i:03d}',
            'agency_id': mec_id if i % 2 == 0 else saude_id,
            'agency_key': 'mec' if i % 2 == 0 else 'saude',
            'agency_name': 'Ministério da Educação' if i % 2 == 0 else 'Ministério da Saúde',
            'theme_l1_id': theme_l1_id,
            'theme_l2_id': theme_l2_id,
            'theme_l3_id': theme_l3_id,
            'theme_l1_code': '01',
            'theme_l1_label': 'Educação',
            'theme_l2_code': '01.01',
            'theme_l2_label': 'Ensino Superior',
            'theme_l3_code': '01.01.01',
            'theme_l3_label': 'Universidades',
            'most_specific_theme_id': theme_l3_id,
            'most_specific_theme_code': '01.01.01',
            'most_specific_theme_label': 'Universidades',
            'title': f'Notícia de teste {i + 1} sobre educação em 2025',
            'url': f'https://www.gov.br/mec/noticias/2025/test-{i}',
            'content': f'Conteúdo completo da notícia {i + 1}. Esta é uma notícia de teste sobre políticas educacionais no Brasil.',
            'summary': f'Resumo da notícia {i + 1} gerado por IA. Aborda temas educacionais importantes.',
            'published_at': f'2025-01-{(i % 28) + 1:02d} 10:00:00+00',
            'extracted_at': f'2025-01-{(i % 28) + 1:02d} 11:00:00+00',
        }
        for i in range(10)
    ]

    # Also insert 3 news from 2024 (these should NOT be processed)
    news_data_2024 = [
        {
            'unique_id': f'test_2024_{i:03d}',
            'agency_id': mec_id,
            'agency_key': 'mec',
            'agency_name': 'Ministério da Educação',
            'title': f'Notícia antiga {i + 1} de 2024',
            'url': f'https://www.gov.br/mec/noticias/2024/test-{i}',
            'content': f'Conteúdo da notícia antiga {i + 1}.',
            'published_at': f'2024-12-{25 + i:02d} 10:00:00+00',
            'extracted_at': f'2024-12-{25 + i:02d} 11:00:00+00',
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
            news
        )

    postgresql.commit()

    # Return the unique_ids of 2025 news
    return [news['unique_id'] for news in news_data]


@pytest.fixture
def mock_sentence_transformer():
    """
    Mock the SentenceTransformer model to avoid downloading the real model.

    Returns a mock that generates random embeddings of shape (batch_size, 768).
    """
    mock_model = MagicMock()

    def mock_encode(texts, batch_size=100, show_progress_bar=False,
                   convert_to_numpy=True, normalize_embeddings=True):
        """Generate fake embeddings for testing."""
        # Generate random embeddings
        embeddings = np.random.randn(len(texts), 768).astype(np.float32)

        # Normalize if requested
        if normalize_embeddings:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / norms

        return embeddings

    mock_model.encode = mock_encode

    return mock_model


@pytest.fixture
def mock_typesense_client():
    """
    Mock the Typesense client to avoid requiring a real Typesense instance.

    Returns a mock that simulates successful document imports.
    """
    mock_client = MagicMock()

    # Mock collection retrieval
    mock_collection = {
        'name': 'news',
        'num_documents': 1000,
        'fields': [
            {'name': 'unique_id', 'type': 'string'},
            {'name': 'title', 'type': 'string'},
            {'name': 'content_embedding', 'type': 'float[]'},
        ]
    }

    mock_client.collections = {
        'news': MagicMock(
            retrieve=Mock(return_value=mock_collection),
            documents=MagicMock()
        )
    }

    # Mock document import (all succeed)
    def mock_import(documents, options):
        """Simulate successful import of all documents."""
        return [{'success': True} for _ in documents]

    mock_client.collections['news'].documents.import_ = mock_import

    return mock_client


class TestEmbeddingWorkflow:
    """Integration tests for the complete embedding workflow."""

    def test_embedding_generator_initialization(self, test_database_url):
        """Test that EmbeddingGenerator can be initialized with test database."""
        with patch('data_platform.jobs.embeddings.embedding_generator.SentenceTransformer'):
            generator = EmbeddingGenerator(database_url=test_database_url)
            assert generator.database_url == test_database_url

    def test_fetch_news_without_embeddings_only_2025(
        self, test_database_url, sample_2025_news, mock_sentence_transformer
    ):
        """
        Test that only 2025 news are fetched for embedding generation.

        This validates the key requirement: only 2025 news should be processed.
        """
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Fetch news without embeddings from 2025-01-01 to 2025-01-31
            news_records = generator._fetch_news_without_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

            # Should get all 10 news from 2025
            assert len(news_records) == 10

            # Verify all records are from 2025
            for record in news_records:
                unique_id = record[0]
                assert unique_id.startswith('test_2025_')

    def test_generate_embeddings_success(
        self, test_database_url, sample_2025_news, mock_sentence_transformer, postgresql
    ):
        """
        Test the complete embedding generation workflow.

        This validates:
        1. Embeddings are generated for all 2025 news
        2. Embeddings are stored in PostgreSQL
        3. embedding_generated_at timestamp is set
        """
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Generate embeddings for January 2025
            result = generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                batch_size=5
            )

            # Verify statistics
            assert result['processed'] == 10
            assert result['successful'] == 10
            assert result['failed'] == 0

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
        self, test_database_url, mock_sentence_transformer
    ):
        """
        Test the text preparation strategy for embeddings.

        Validates: title + " " + summary (fallback to content if summary missing)
        """
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Test with summary
            text1 = generator._prepare_text_for_embedding(
                title="Test Title",
                summary="Test Summary",
                content="Test Content"
            )
            assert text1 == "Test Title Test Summary"

            # Test without summary (fallback to content)
            text2 = generator._prepare_text_for_embedding(
                title="Test Title",
                summary=None,
                content="Test Content Here"
            )
            assert text2 == "Test Title Test Content Here"

            # Test with empty summary (fallback to content)
            text3 = generator._prepare_text_for_embedding(
                title="Test Title",
                summary="   ",
                content="Test Content"
            )
            assert text3 == "Test Title Test Content"

    def test_typesense_sync_initialization(self, test_database_url):
        """Test that TypesenseSyncManager can be initialized."""
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense'):
            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )
            assert sync_manager.database_url == test_database_url

    def test_fetch_news_with_embeddings(
        self, test_database_url, sample_2025_news, mock_sentence_transformer,
        mock_typesense_client, postgresql
    ):
        """
        Test fetching news that have embeddings for Typesense sync.
        """
        # First generate embeddings
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)
            generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

        # Now fetch for sync
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            # Fetch news with embeddings
            news_records = sync_manager._fetch_news_with_new_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

            # Should get all 10 news with embeddings
            assert len(news_records) == 10

            # Verify all have embeddings
            for record in news_records:
                assert record['content_embedding'] is not None

    def test_typesense_document_preparation(
        self, test_database_url, sample_2025_news, mock_sentence_transformer,
        mock_typesense_client, postgresql
    ):
        """
        Test preparing news records as Typesense documents.

        Validates the document format is correct.
        """
        # First generate embeddings
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)
            generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

        # Prepare documents
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            # Get first news record
            news_records = sync_manager._fetch_news_with_new_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                limit=1
            )

            assert len(news_records) == 1
            news = news_records[0]

            # Prepare as Typesense document
            doc = sync_manager._prepare_typesense_document(news)

            # Verify required fields
            assert 'unique_id' in doc
            assert 'published_at' in doc
            assert isinstance(doc['published_at'], int)  # Unix timestamp

            # Verify optional fields
            assert 'title' in doc
            assert 'agency_key' in doc
            assert 'content' in doc
            assert 'summary' in doc

            # Verify theme fields
            assert 'theme_l1_code' in doc
            assert 'theme_l1_label' in doc
            assert 'most_specific_theme_code' in doc

            # Verify embedding field
            assert 'content_embedding' in doc
            assert isinstance(doc['content_embedding'], list)
            assert len(doc['content_embedding']) == 768

    def test_complete_workflow_generate_and_sync(
        self, test_database_url, sample_2025_news, mock_sentence_transformer,
        mock_typesense_client, postgresql
    ):
        """
        MAIN INTEGRATION TEST: Test the complete workflow.

        This test validates:
        1. Generate embeddings for 2025 news
        2. Sync those embeddings to Typesense
        3. Verify data flows correctly through the entire pipeline
        """
        # Step 1: Generate embeddings
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            gen_result = generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                batch_size=5
            )

            # Verify generation succeeded
            assert gen_result['successful'] == 10
            assert gen_result['failed'] == 0

        # Step 2: Sync to Typesense
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            sync_result = sync_manager.sync_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                batch_size=5
            )

            # Verify sync succeeded
            assert sync_result['successful'] == 10
            assert sync_result['failed'] == 0
            assert sync_result['processed'] == 10

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

    def test_incremental_sync(
        self, test_database_url, sample_2025_news, mock_sentence_transformer,
        mock_typesense_client, postgresql
    ):
        """
        Test incremental sync (only sync newly updated embeddings).

        Validates that we can efficiently sync only what changed.
        """
        # Step 1: Generate embeddings
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)
            generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

        # Step 2: First full sync
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            # Full sync
            sync_result1 = sync_manager.sync_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                full_sync=True
            )
            assert sync_result1['successful'] == 10

            # Record sync in sync_log
            cur = postgresql.cursor()
            cur.execute("""
                INSERT INTO sync_log (operation, status, completed_at)
                VALUES ('typesense_embeddings_sync', 'completed', NOW())
            """)
            postgresql.commit()

            # Step 3: Incremental sync (should find nothing new)
            sync_result2 = sync_manager.sync_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                full_sync=False  # Incremental
            )

            # No new embeddings to sync
            assert sync_result2['processed'] == 0

    def test_batch_processing(
        self, test_database_url, sample_2025_news, mock_sentence_transformer,
        mock_typesense_client
    ):
        """
        Test that batch processing works correctly.

        Validates that large datasets are processed in batches.
        """
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Generate with small batch size
            result = generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                batch_size=3  # Small batch to test multiple batches
            )

            # Should still process all 10 records
            assert result['successful'] == 10

        # Test Typesense sync with small batches
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            sync_result = sync_manager.sync_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31',
                batch_size=3
            )

            assert sync_result['successful'] == 10


class TestEmbeddingWorkflowEdgeCases:
    """Test edge cases and error scenarios."""

    def test_generate_embeddings_no_records(
        self, test_database_url, mock_sentence_transformer
    ):
        """Test generating embeddings when no records need processing."""
        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Try to generate for a date range with no data
            result = generator.generate_embeddings(
                start_date='2025-12-01',
                end_date='2025-12-31'
            )

            assert result['processed'] == 0
            assert result['successful'] == 0
            assert result['failed'] == 0

    def test_sync_no_embeddings(self, test_database_url, mock_typesense_client):
        """Test syncing when no embeddings exist."""
        with patch('data_platform.jobs.embeddings.typesense_sync.typesense.Client') as mock_ts:
            mock_ts.return_value = mock_typesense_client

            sync_manager = TypesenseSyncManager(
                database_url=test_database_url,
                typesense_api_key='test_key'
            )

            result = sync_manager.sync_embeddings(
                start_date='2025-12-01',
                end_date='2025-12-31'
            )

            assert result['processed'] == 0

    def test_embedding_with_missing_summary(
        self, test_database_url, sample_2025_news, mock_sentence_transformer, postgresql
    ):
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

        with patch(
            'data_platform.jobs.embeddings.embedding_generator.SentenceTransformer',
            return_value=mock_sentence_transformer
        ):
            generator = EmbeddingGenerator(database_url=test_database_url)

            # Should still succeed (fallback to content)
            result = generator.generate_embeddings(
                start_date='2025-01-01',
                end_date='2025-01-31'
            )

            assert result['successful'] == 10
            assert result['failed'] == 0
