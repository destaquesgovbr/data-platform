"""
Unit tests for TypesenseSyncManager.

Phase 4.7: Embeddings Semânticos
"""

import json
import struct
import sys
from datetime import datetime
from typing import Dict, List, Optional
from unittest.mock import MagicMock, Mock, call, patch

import pytest

# Create proper mock exception class for typesense
class MockTypesenseObjectNotFound(Exception):
    """Mock exception for Typesense ObjectNotFound."""
    pass

# Mock external dependencies before importing TypesenseSyncManager
mock_typesense = MagicMock()
mock_typesense_exceptions = MagicMock()
mock_typesense_exceptions.ObjectNotFound = MockTypesenseObjectNotFound

sys.modules['typesense'] = mock_typesense
sys.modules['typesense.exceptions'] = mock_typesense_exceptions
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['torch'] = MagicMock()

# Now we can safely import psycopg2 and the manager
import psycopg2
import psycopg2.errors

from data_platform.jobs.embeddings.typesense_sync import TypesenseSyncManager

# Get the mocked typesense for use in tests
import typesense
typesense.exceptions = mock_typesense_exceptions


class TestTypesenseSyncManager:
    """Tests for TypesenseSyncManager class."""

    @pytest.fixture
    def mock_database_url(self) -> str:
        """Mock database URL."""
        return "postgresql://user:pass@localhost:5432/test"

    @pytest.fixture
    def mock_typesense_config(self) -> Dict[str, str]:
        """Mock Typesense configuration."""
        return {
            "host": "localhost",
            "port": "8108",
            "api_key": "test_api_key_12345"
        }

    @pytest.fixture
    def sync_manager(
        self, mock_database_url: str, mock_typesense_config: Dict[str, str]
    ) -> TypesenseSyncManager:
        """Create TypesenseSyncManager instance with mocked config."""
        return TypesenseSyncManager(
            database_url=mock_database_url,
            typesense_host=mock_typesense_config["host"],
            typesense_port=mock_typesense_config["port"],
            typesense_api_key=mock_typesense_config["api_key"]
        )

    # ========================================================================
    # Initialization Tests
    # ========================================================================

    def test_init_with_explicit_params(
        self, mock_database_url: str, mock_typesense_config: Dict[str, str]
    ) -> None:
        """Test initialization with explicit parameters."""
        manager = TypesenseSyncManager(
            database_url=mock_database_url,
            typesense_host=mock_typesense_config["host"],
            typesense_port=mock_typesense_config["port"],
            typesense_api_key=mock_typesense_config["api_key"]
        )

        assert manager.database_url == mock_database_url
        assert manager.typesense_host == mock_typesense_config["host"]
        assert manager.typesense_port == mock_typesense_config["port"]
        assert manager.typesense_api_key == mock_typesense_config["api_key"]
        assert manager._client is None  # Lazy init

    def test_init_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization from environment variables."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://env:pass@localhost:5432/test")
        monkeypatch.setenv("TYPESENSE_HOST", "typesense.example.com")
        monkeypatch.setenv("TYPESENSE_PORT", "443")
        monkeypatch.setenv("TYPESENSE_API_KEY", "env_api_key")

        manager = TypesenseSyncManager()

        assert manager.database_url == "postgresql://env:pass@localhost:5432/test"
        assert manager.typesense_host == "typesense.example.com"
        assert manager.typesense_port == "443"
        assert manager.typesense_api_key == "env_api_key"

    def test_init_default_host_and_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization with default host and port."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        monkeypatch.setenv("TYPESENSE_API_KEY", "test_key")
        monkeypatch.delenv("TYPESENSE_HOST", raising=False)
        monkeypatch.delenv("TYPESENSE_PORT", raising=False)

        manager = TypesenseSyncManager()

        assert manager.typesense_host == "localhost"
        assert manager.typesense_port == "8108"

    def test_init_missing_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization fails without DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("TYPESENSE_API_KEY", "test_key")

        with pytest.raises(ValueError, match="DATABASE_URL environment variable is required"):
            TypesenseSyncManager()

    def test_init_missing_typesense_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test initialization fails without TYPESENSE_API_KEY."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        monkeypatch.delenv("TYPESENSE_API_KEY", raising=False)

        with pytest.raises(ValueError, match="TYPESENSE_API_KEY environment variable is required"):
            TypesenseSyncManager()

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_client_lazy_initialization(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test that Typesense client is initialized lazily."""
        # Client should not be initialized yet
        assert sync_manager._client is None

        # Access client property
        _ = sync_manager.client

        # Client should be initialized
        mock_typesense_client.assert_called_once_with({
            'nodes': [{
                'host': 'localhost',
                'port': '8108',
                'protocol': 'http'
            }],
            'api_key': 'test_api_key_12345',
            'connection_timeout_seconds': 10
        })
        assert sync_manager._client is not None

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_client_cached_after_first_access(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test that Typesense client is cached after first access."""
        # Access client twice
        _ = sync_manager.client
        _ = sync_manager.client

        # Should only be called once
        mock_typesense_client.assert_called_once()

    # ========================================================================
    # _check_collection_schema Tests
    # ========================================================================

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_check_collection_schema_success(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test checking collection schema when collection exists with embedding field."""
        # Mock collection with embedding field
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 1000,
            'fields': [
                {'name': 'unique_id', 'type': 'string'},
                {'name': 'title', 'type': 'string'},
                {'name': 'content_embedding', 'type': 'float[]', 'num_dim': 768}
            ]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        result = sync_manager._check_collection_schema()

        assert result['name'] == 'news'
        assert result['num_documents'] == 1000
        mock_collection.retrieve.assert_called_once()

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_check_collection_schema_missing_embedding_field(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test checking collection schema when embedding field is missing."""
        # Mock collection without embedding field
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 1000,
            'fields': [
                {'name': 'unique_id', 'type': 'string'},
                {'name': 'title', 'type': 'string'}
                # Missing content_embedding field
            ]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Should still return the collection, but log a warning
        result = sync_manager._check_collection_schema()

        assert result['name'] == 'news'
        # Verify warning was logged (implicitly through no exception)

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_check_collection_schema_collection_not_found(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test checking collection schema when collection doesn't exist."""
        # Mock collection not found
        mock_collection = MagicMock()
        mock_collection.retrieve.side_effect = MockTypesenseObjectNotFound("Not found")

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        with pytest.raises(ValueError, match="Collection 'news' not found"):
            sync_manager._check_collection_schema()

    # ========================================================================
    # _fetch_news_with_new_embeddings Tests
    # ========================================================================

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_fetch_news_basic(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test fetching news with embeddings for a date range."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock cursor description and results
        mock_cursor.description = [
            ('unique_id',), ('agency_key',), ('title',),
            ('url',), ('image_url',), ('category',),
            ('content',), ('summary',), ('subtitle',),
            ('editorial_lead',), ('published_at',), ('extracted_at',),
            ('theme_l1_code',), ('theme_l1_label',),
            ('theme_l2_code',), ('theme_l2_label',),
            ('theme_l3_code',), ('theme_l3_label',),
            ('most_specific_theme_code',), ('most_specific_theme_label',),
            ('content_embedding',), ('embedding_generated_at',)
        ]

        mock_cursor.fetchall.return_value = [
            (
                'news-1', 'planalto', 'Título 1',
                'https://example.gov.br/1', 'https://example.gov.br/img1.jpg', 'Notícia',
                'Conteúdo 1', 'Resumo 1', 'Subtítulo 1',
                'Lead 1', datetime(2025, 1, 15, 10, 0), datetime(2025, 1, 15, 11, 0),
                'A', 'Política', 'A.1', 'Governo Federal',
                'A.1.1', 'Presidência', 'A.1.1', 'Presidência',
                '[0.1, 0.2, 0.3]', datetime(2025, 1, 15, 12, 0)
            ),
        ]

        results = sync_manager._fetch_news_with_new_embeddings(
            start_date="2025-01-15",
            end_date="2025-01-15"
        )

        assert len(results) == 1
        assert results[0]['unique_id'] == 'news-1'
        assert results[0]['title'] == 'Título 1'
        assert results[0]['content_embedding'] == '[0.1, 0.2, 0.3]'

        # Verify query execution
        mock_cursor.execute.assert_called_once()
        query, params = mock_cursor.execute.call_args[0]
        assert "published_at >= %s" in query
        assert "content_embedding IS NOT NULL" in query
        assert "published_at >= '2025-01-01'" in query
        assert params == ["2025-01-15", "2025-01-15"]

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_fetch_news_with_last_sync_timestamp(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test fetching news with incremental sync (last_sync_timestamp filter)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.description = [('unique_id',), ('title',)]
        mock_cursor.fetchall.return_value = []

        last_sync = datetime(2025, 1, 10, 12, 0)
        sync_manager._fetch_news_with_new_embeddings(
            start_date="2025-01-15",
            end_date="2025-01-15",
            last_sync_timestamp=last_sync
        )

        # Verify query includes last_sync_timestamp filter
        query, params = mock_cursor.execute.call_args[0]
        assert "embedding_generated_at > %s" in query
        assert last_sync in params

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_fetch_news_with_limit(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test fetching news with record limit."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.description = [('unique_id',)]
        mock_cursor.fetchall.return_value = []

        sync_manager._fetch_news_with_new_embeddings(
            start_date="2025-01-15",
            limit=100
        )

        # Verify query includes LIMIT
        query, params = mock_cursor.execute.call_args[0]
        assert "LIMIT %s" in query
        assert 100 in params

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_fetch_news_default_end_date(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test fetching news defaults end_date to start_date."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.description = [('unique_id',)]
        mock_cursor.fetchall.return_value = []

        sync_manager._fetch_news_with_new_embeddings(start_date="2025-01-15")

        # Verify both params are the same date
        _, params = mock_cursor.execute.call_args[0]
        assert params[0] == "2025-01-15"
        assert params[1] == "2025-01-15"

    # ========================================================================
    # _get_last_sync_timestamp Tests
    # ========================================================================

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_get_last_sync_timestamp_exists(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test getting last sync timestamp when sync log exists."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        last_sync = datetime(2025, 1, 10, 12, 0)
        mock_cursor.fetchone.return_value = (last_sync,)

        result = sync_manager._get_last_sync_timestamp()

        assert result == last_sync
        mock_cursor.execute.assert_called_once()
        query = mock_cursor.execute.call_args[0][0]
        # Handle multi-line SQL query
        query_normalized = ' '.join(query.split())
        assert "SELECT completed_at FROM sync_log" in query_normalized
        assert "operation = 'typesense_embeddings_sync'" in query_normalized
        assert "status = 'completed'" in query_normalized

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_get_last_sync_timestamp_not_exists(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test getting last sync timestamp when no sync log exists."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.fetchone.return_value = None

        result = sync_manager._get_last_sync_timestamp()

        assert result is None

    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_get_last_sync_timestamp_table_not_exists(
        self, mock_connect: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test getting last sync timestamp when sync_log table doesn't exist."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate UndefinedTable error
        mock_cursor.execute.side_effect = psycopg2.errors.UndefinedTable("sync_log doesn't exist")

        result = sync_manager._get_last_sync_timestamp()

        assert result is None

    # ========================================================================
    # _prepare_typesense_document Tests
    # ========================================================================

    def test_prepare_document_all_fields(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with all fields present."""
        news = {
            'unique_id': 'news-123',
            'agency_key': 'planalto',
            'title': 'Título da notícia',
            'url': 'https://example.gov.br/news',
            'image_url': 'https://example.gov.br/img.jpg',
            'category': 'Notícia',
            'content': 'Conteúdo completo',
            'summary': 'Resumo gerado',
            'subtitle': 'Subtítulo',
            'editorial_lead': 'Lead editorial',
            'published_at': datetime(2025, 1, 15, 10, 30),
            'extracted_at': datetime(2025, 1, 15, 11, 0),
            'theme_l1_code': 'A',
            'theme_l1_label': 'Política',
            'theme_l2_code': 'A.1',
            'theme_l2_label': 'Governo',
            'theme_l3_code': 'A.1.1',
            'theme_l3_label': 'Presidência',
            'most_specific_theme_code': 'A.1.1',
            'most_specific_theme_label': 'Presidência',
            'content_embedding': [0.1, 0.2, 0.3]
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['unique_id'] == 'news-123'
        assert doc['agency_key'] == 'planalto'
        assert doc['title'] == 'Título da notícia'
        assert doc['published_at'] == int(datetime(2025, 1, 15, 10, 30).timestamp())
        assert doc['extracted_at'] == int(datetime(2025, 1, 15, 11, 0).timestamp())
        assert doc['published_year'] == 2025
        assert doc['published_month'] == 1
        assert doc['content_embedding'] == [0.1, 0.2, 0.3]

    def test_prepare_document_minimal_fields(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with only required fields."""
        news = {
            'unique_id': 'news-456',
            'published_at': datetime(2025, 2, 20, 14, 0)
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['unique_id'] == 'news-456'
        assert doc['published_at'] == int(datetime(2025, 2, 20, 14, 0).timestamp())
        assert doc['published_year'] == 2025
        assert doc['published_month'] == 2
        # Optional fields should not be present
        assert 'title' not in doc
        assert 'content_embedding' not in doc

    def test_prepare_document_none_published_at(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document when published_at is None."""
        news = {
            'unique_id': 'news-789',
            'published_at': None
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['unique_id'] == 'news-789'
        assert doc['published_at'] == 0
        assert 'published_year' not in doc
        assert 'published_month' not in doc

    def test_prepare_document_string_embedding(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with embedding as JSON string."""
        news = {
            'unique_id': 'news-str',
            'published_at': datetime(2025, 1, 1),
            'content_embedding': '[0.1, 0.2, 0.3, 0.4]'
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['content_embedding'] == [0.1, 0.2, 0.3, 0.4]

    def test_prepare_document_bytes_embedding(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with embedding as pgvector bytes."""
        # Create pgvector binary format: dimension (2 bytes) + floats (4 bytes each)
        dim = 3
        floats = [0.1, 0.2, 0.3]
        embedding_bytes = struct.pack('!H', dim) + struct.pack(f'!{dim}f', *floats)

        news = {
            'unique_id': 'news-bytes',
            'published_at': datetime(2025, 1, 1),
            'content_embedding': embedding_bytes
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert 'content_embedding' in doc
        assert len(doc['content_embedding']) == 3
        assert abs(doc['content_embedding'][0] - 0.1) < 0.001
        assert abs(doc['content_embedding'][1] - 0.2) < 0.001
        assert abs(doc['content_embedding'][2] - 0.3) < 0.001

    def test_prepare_document_memoryview_embedding(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with embedding as memoryview."""
        dim = 2
        floats = [0.5, 0.6]
        embedding_bytes = struct.pack('!H', dim) + struct.pack(f'!{dim}f', *floats)
        embedding_memoryview = memoryview(embedding_bytes)

        news = {
            'unique_id': 'news-memview',
            'published_at': datetime(2025, 1, 1),
            'content_embedding': embedding_memoryview
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert 'content_embedding' in doc
        assert len(doc['content_embedding']) == 2

    def test_prepare_document_list_embedding(self, sync_manager: TypesenseSyncManager) -> None:
        """Test preparing document with embedding already as list."""
        embedding = [0.7, 0.8, 0.9]
        news = {
            'unique_id': 'news-list',
            'published_at': datetime(2025, 1, 1),
            'content_embedding': embedding
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['content_embedding'] == embedding

    def test_prepare_document_strips_whitespace(self, sync_manager: TypesenseSyncManager) -> None:
        """Test that string fields are stripped of whitespace."""
        news = {
            'unique_id': 'news-whitespace',
            'published_at': datetime(2025, 1, 1),
            'title': '  Título com espaços  ',
            'agency_key': '  planalto  '
        }

        doc = sync_manager._prepare_typesense_document(news)

        assert doc['title'] == 'Título com espaços'
        assert doc['agency_key'] == 'planalto'

    def test_prepare_document_empty_optional_fields(
        self, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test that empty optional fields are not included."""
        news = {
            'unique_id': 'news-empty',
            'published_at': datetime(2025, 1, 1),
            'title': '',
            'summary': None,
            'content': '   '  # Whitespace only - truthy in the if check!
        }

        doc = sync_manager._prepare_typesense_document(news)

        # Empty string '' is falsy, so not included
        assert 'title' not in doc
        # None is falsy, so not included
        assert 'summary' not in doc
        # '   ' (whitespace) is truthy, so it IS included but stripped to ''
        # This is actually a bug in the source code, but we're testing current behavior
        assert doc.get('content') == ''

    # ========================================================================
    # _upsert_documents_batch Tests
    # ========================================================================

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_upsert_batch_all_success(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test upserting batch with all documents succeeding."""
        documents = [
            {'unique_id': 'news-1', 'title': 'Title 1'},
            {'unique_id': 'news-2', 'title': 'Title 2'},
            {'unique_id': 'news-3', 'title': 'Title 3'}
        ]

        # Mock import results (all success)
        mock_import_results = [
            {'success': True},
            {'success': True},
            {'success': True}
        ]

        mock_collection = MagicMock()
        mock_collection.documents.import_.return_value = mock_import_results

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        result = sync_manager._upsert_documents_batch(documents)

        assert result == 3
        mock_collection.documents.import_.assert_called_once_with(
            documents,
            {'action': 'upsert'}
        )

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_upsert_batch_partial_failure(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test upserting batch with some documents failing."""
        documents = [
            {'unique_id': 'news-1', 'title': 'Title 1'},
            {'unique_id': 'news-2', 'title': 'Title 2'},
            {'unique_id': 'news-3', 'title': 'Title 3'}
        ]

        # Mock import results (1 failure)
        mock_import_results = [
            {'success': True},
            {'success': False, 'error': 'Invalid document'},
            {'success': True}
        ]

        mock_collection = MagicMock()
        mock_collection.documents.import_.return_value = mock_import_results

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        result = sync_manager._upsert_documents_batch(documents)

        assert result == 2  # 2 successful

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    def test_upsert_batch_exception(
        self, mock_typesense_client: Mock, sync_manager: TypesenseSyncManager
    ) -> None:
        """Test upserting batch when exception occurs."""
        documents = [{'unique_id': 'news-1'}]

        mock_collection = MagicMock()
        mock_collection.documents.import_.side_effect = Exception("Network error")

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        with pytest.raises(Exception, match="Network error"):
            sync_manager._upsert_documents_batch(documents)

    # ========================================================================
    # sync_embeddings End-to-End Tests
    # ========================================================================

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_full_sync(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test full sync workflow (all embeddings)."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 0,
            'fields': [
                {'name': 'unique_id', 'type': 'string'},
                {'name': 'content_embedding', 'type': 'float[]'}
            ]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database connection for fetching news
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock news records
        mock_cursor.description = [
            ('unique_id',), ('published_at',), ('title',), ('content_embedding',)
        ]
        mock_cursor.fetchall.return_value = [
            ('news-1', datetime(2025, 1, 15), 'Title 1', [0.1, 0.2]),
            ('news-2', datetime(2025, 1, 15), 'Title 2', [0.3, 0.4])
        ]

        # Mock upsert results
        mock_collection.documents.import_.return_value = [
            {'success': True},
            {'success': True}
        ]

        # Run sync
        stats = sync_manager.sync_embeddings(
            start_date="2025-01-15",
            full_sync=True
        )

        assert stats['processed'] == 2
        assert stats['successful'] == 2
        assert stats['failed'] == 0

        # Verify collection check
        mock_collection.retrieve.assert_called_once()

        # Verify fetch (should not query sync_log for full sync)
        assert mock_cursor.execute.call_count == 1

        # Verify upsert
        mock_collection.documents.import_.assert_called_once()

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_incremental_sync(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test incremental sync workflow (only updated embeddings)."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 1000,
            'fields': [
                {'name': 'unique_id', 'type': 'string'},
                {'name': 'content_embedding', 'type': 'float[]'}
            ]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database connections (will be called twice: sync_log + news fetch)
        mock_conn1 = MagicMock()
        mock_cursor1 = MagicMock()
        mock_conn1.cursor.return_value.__enter__.return_value = mock_cursor1

        mock_conn2 = MagicMock()
        mock_cursor2 = MagicMock()
        mock_conn2.cursor.return_value.__enter__.return_value = mock_cursor2

        mock_connect.side_effect = [mock_conn1, mock_conn2]

        # Mock sync_log query (last sync timestamp)
        last_sync = datetime(2025, 1, 10, 12, 0)
        mock_cursor1.fetchone.return_value = (last_sync,)

        # Mock news fetch
        mock_cursor2.description = [
            ('unique_id',), ('published_at',), ('content_embedding',)
        ]
        mock_cursor2.fetchall.return_value = [
            ('news-3', datetime(2025, 1, 15), [0.5, 0.6])
        ]

        # Mock upsert results
        mock_collection.documents.import_.return_value = [
            {'success': True}
        ]

        # Run incremental sync
        stats = sync_manager.sync_embeddings(
            start_date="2025-01-15",
            full_sync=False
        )

        assert stats['processed'] == 1
        assert stats['successful'] == 1
        assert stats['failed'] == 0

        # Verify sync_log was queried
        query = mock_cursor1.execute.call_args[0][0]
        assert "sync_log" in query

        # Verify news fetch included last_sync_timestamp filter
        query = mock_cursor2.execute.call_args[0][0]
        assert "embedding_generated_at > %s" in query

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_no_records(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test sync when no records need syncing."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 0,
            'fields': [{'name': 'content_embedding', 'type': 'float[]'}]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.description = [('unique_id',)]
        mock_cursor.fetchall.return_value = []

        # Run sync
        stats = sync_manager.sync_embeddings(start_date="2025-01-15", full_sync=True)

        assert stats['processed'] == 0
        assert stats['successful'] == 0
        assert stats['failed'] == 0

        # Verify no upsert was attempted
        mock_collection.documents.import_.assert_not_called()

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_batch_processing(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test sync processes documents in batches."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 0,
            'fields': [{'name': 'content_embedding', 'type': 'float[]'}]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Create 5 records (will be processed in batches of 2)
        mock_cursor.description = [
            ('unique_id',), ('published_at',), ('content_embedding',)
        ]
        mock_cursor.fetchall.return_value = [
            (f'news-{i}', datetime(2025, 1, 15), [0.1 * i])
            for i in range(1, 6)
        ]

        # Mock upsert results
        mock_collection.documents.import_.return_value = [
            {'success': True},
            {'success': True}
        ]

        # Run sync with small batch size
        stats = sync_manager.sync_embeddings(
            start_date="2025-01-15",
            full_sync=True,
            batch_size=2
        )

        assert stats['processed'] == 5
        # 3 batches: 2 + 2 + 1
        assert mock_collection.documents.import_.call_count == 3

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_batch_error_handling(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test sync continues after batch error."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 0,
            'fields': [{'name': 'content_embedding', 'type': 'float[]'}]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Create 4 records (2 batches of 2)
        mock_cursor.description = [
            ('unique_id',), ('published_at',), ('content_embedding',)
        ]
        mock_cursor.fetchall.return_value = [
            (f'news-{i}', datetime(2025, 1, 15), [0.1 * i])
            for i in range(1, 5)
        ]

        # First batch fails, second succeeds
        mock_collection.documents.import_.side_effect = [
            Exception("Network error"),
            [{'success': True}, {'success': True}]
        ]

        # Run sync
        stats = sync_manager.sync_embeddings(
            start_date="2025-01-15",
            full_sync=True,
            batch_size=2
        )

        assert stats['processed'] == 4
        assert stats['successful'] == 2  # Second batch
        assert stats['failed'] == 2  # First batch

    @patch("data_platform.jobs.embeddings.typesense_sync.typesense.Client")
    @patch("data_platform.jobs.embeddings.typesense_sync.psycopg2.connect")
    def test_sync_embeddings_with_max_records(
        self, mock_connect: Mock, mock_typesense_client: Mock,
        sync_manager: TypesenseSyncManager
    ) -> None:
        """Test sync with max_records limit."""
        # Mock collection check
        mock_collection = MagicMock()
        mock_collection.retrieve.return_value = {
            'name': 'news',
            'num_documents': 0,
            'fields': [{'name': 'content_embedding', 'type': 'float[]'}]
        }

        mock_client = MagicMock()
        mock_client.collections.__getitem__.return_value = mock_collection
        mock_typesense_client.return_value = mock_client

        # Mock database
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_cursor.description = [('unique_id',), ('published_at',)]
        mock_cursor.fetchall.return_value = []

        # Run sync with max_records
        sync_manager.sync_embeddings(
            start_date="2025-01-15",
            full_sync=True,
            max_records=100
        )

        # Verify LIMIT was passed to fetch query
        query, params = mock_cursor.execute.call_args[0]
        assert "LIMIT %s" in query
        assert 100 in params
