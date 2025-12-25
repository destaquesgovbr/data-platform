"""
Tests for StorageAdapter.
"""

import os
from collections import OrderedDict
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import pandas as pd
import pytest

from data_platform.managers.storage_adapter import StorageAdapter, StorageBackend


class TestStorageBackendEnum:
    """Test StorageBackend enum."""

    def test_backend_values(self):
        """Test enum values."""
        assert StorageBackend.HUGGINGFACE.value == "huggingface"
        assert StorageBackend.POSTGRES.value == "postgres"
        assert StorageBackend.DUAL_WRITE.value == "dual_write"

    def test_backend_from_string(self):
        """Test creating backend from string."""
        assert StorageBackend("huggingface") == StorageBackend.HUGGINGFACE
        assert StorageBackend("postgres") == StorageBackend.POSTGRES
        assert StorageBackend("dual_write") == StorageBackend.DUAL_WRITE


class TestStorageAdapterInit:
    """Test StorageAdapter initialization."""

    def test_default_backend_huggingface(self, monkeypatch):
        """Test default backend is HuggingFace."""
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.delenv("STORAGE_READ_FROM", raising=False)

        adapter = StorageAdapter()
        assert adapter.backend == StorageBackend.HUGGINGFACE
        assert adapter.read_from == StorageBackend.HUGGINGFACE

    def test_backend_from_env(self, monkeypatch):
        """Test backend from environment variable."""
        monkeypatch.setenv("STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("STORAGE_READ_FROM", "postgres")

        adapter = StorageAdapter()
        assert adapter.backend == StorageBackend.POSTGRES
        assert adapter.read_from == StorageBackend.POSTGRES

    def test_dual_write_backend(self, monkeypatch):
        """Test dual-write mode."""
        monkeypatch.setenv("STORAGE_BACKEND", "dual_write")
        monkeypatch.setenv("STORAGE_READ_FROM", "huggingface")

        adapter = StorageAdapter()
        assert adapter.backend == StorageBackend.DUAL_WRITE
        assert adapter.read_from == StorageBackend.HUGGINGFACE

    def test_explicit_backend_override(self, monkeypatch):
        """Test explicit backend overrides env var."""
        monkeypatch.setenv("STORAGE_BACKEND", "huggingface")

        adapter = StorageAdapter(backend=StorageBackend.POSTGRES)
        assert adapter.backend == StorageBackend.POSTGRES


class TestStorageAdapterPostgres:
    """Test StorageAdapter with PostgreSQL backend."""

    @pytest.fixture
    def mock_postgres(self):
        """Create mock PostgresManager."""
        mock = Mock()
        mock.insert.return_value = 10
        mock.update.return_value = True
        mock.get.return_value = []
        mock.get_count.return_value = 100
        mock.load_cache = Mock()
        mock._themes_by_id = {}
        return mock

    @pytest.fixture
    def adapter(self, mock_postgres, monkeypatch):
        """Create adapter with mocked PostgresManager."""
        monkeypatch.setenv("STORAGE_BACKEND", "postgres")
        monkeypatch.setenv("STORAGE_READ_FROM", "postgres")

        adapter = StorageAdapter(postgres_manager=mock_postgres)
        return adapter

    def test_insert_postgres(self, adapter, mock_postgres):
        """Test insert to PostgreSQL."""
        data = OrderedDict({
            "unique_id": ["abc123"],
            "agency": ["test_agency"],
            "title": ["Test Title"],
            "published_at": [datetime.now()],
        })

        result = adapter.insert(data)

        assert mock_postgres.insert.called
        assert result == 10

    def test_update_postgres(self, adapter, mock_postgres):
        """Test update to PostgreSQL."""
        df = pd.DataFrame({
            "unique_id": ["abc123"],
            "title": ["Updated Title"],
        })

        result = adapter.update(df)

        assert mock_postgres.update.called
        assert result == 1

    def test_get_postgres(self, adapter, mock_postgres):
        """Test get from PostgreSQL."""
        result = adapter.get("2024-01-01", "2024-12-31")

        assert mock_postgres.get.called
        assert isinstance(result, pd.DataFrame)


class TestStorageAdapterDualWrite:
    """Test StorageAdapter in dual-write mode."""

    @pytest.fixture
    def mock_postgres(self):
        """Create mock PostgresManager."""
        mock = Mock()
        mock.insert.return_value = 10
        mock.load_cache = Mock()
        return mock

    @pytest.fixture
    def mock_hf(self):
        """Create mock DatasetManager."""
        mock = Mock()
        mock.insert = Mock()
        return mock

    @pytest.fixture
    def adapter(self, mock_postgres, mock_hf, monkeypatch):
        """Create adapter in dual-write mode."""
        monkeypatch.setenv("STORAGE_BACKEND", "dual_write")
        monkeypatch.setenv("STORAGE_READ_FROM", "huggingface")

        adapter = StorageAdapter(
            postgres_manager=mock_postgres,
            dataset_manager=mock_hf,
        )
        return adapter

    def test_insert_dual_write(self, adapter, mock_postgres, mock_hf):
        """Test insert writes to both backends."""
        data = OrderedDict({
            "unique_id": ["abc123"],
            "agency": ["test_agency"],
            "title": ["Test Title"],
            "published_at": [datetime.now()],
        })

        result = adapter.insert(data)

        # Both backends should be called
        assert mock_hf.insert.called
        assert mock_postgres.insert.called

    def test_insert_dual_write_partial_failure(self, adapter, mock_postgres, mock_hf):
        """Test dual-write continues if one backend fails."""
        mock_hf.insert.side_effect = Exception("HuggingFace error")

        data = OrderedDict({
            "unique_id": ["abc123"],
            "agency": ["test_agency"],
            "title": ["Test Title"],
            "published_at": [datetime.now()],
        })

        # Should not raise, PostgreSQL still succeeds
        result = adapter.insert(data)

        assert mock_postgres.insert.called
        assert result == 10


class TestDataConversion:
    """Test data conversion helpers."""

    @pytest.fixture
    def mock_postgres_with_cache(self):
        """Create mock PostgresManager with agency cache."""
        from data_platform.models.news import Agency, Theme

        mock = Mock()
        # Create mock agencies
        agency1 = Mock()
        agency1.id = 1
        agency1.name = "Agency 1"
        agency2 = Mock()
        agency2.id = 2
        agency2.name = "Agency 2"

        mock._agencies_by_key = {
            "agency1": agency1,
            "agency2": agency2,
        }
        mock._themes_by_code = {}
        return mock

    @pytest.fixture
    def adapter(self, mock_postgres_with_cache, monkeypatch):
        """Create adapter for conversion tests."""
        monkeypatch.setenv("STORAGE_BACKEND", "postgres")
        return StorageAdapter(postgres_manager=mock_postgres_with_cache)

    def test_parse_datetime_none(self, adapter):
        """Test parsing None datetime."""
        result = adapter._parse_datetime(None)
        assert result is None

    def test_parse_datetime_string(self, adapter):
        """Test parsing datetime string."""
        result = adapter._parse_datetime("2024-01-15T10:30:00Z")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_datetime(self, adapter):
        """Test parsing datetime object."""
        dt = datetime(2024, 6, 15, 12, 0, 0)
        result = adapter._parse_datetime(dt)
        assert result == dt

    def test_convert_to_news_insert(self, adapter):
        """Test converting OrderedDict to NewsInsert list."""
        now = datetime.now()
        data = OrderedDict({
            "unique_id": ["abc123", "def456"],
            "agency": ["agency1", "agency2"],
            "title": ["Title 1", "Title 2"],
            "published_at": [now, now],
            "image": ["http://img1.jpg", "http://img2.jpg"],
            "url": [None, None],
            "video_url": [None, None],
            "category": [None, None],
            "tags": [[], []],
            "content": [None, None],
            "editorial_lead": [None, None],
            "subtitle": [None, None],
            "summary": [None, None],
            "updated_datetime": [None, None],
            "extracted_at": [None, None],
            "theme_1_level_1_code": [None, None],
            "theme_1_level_2_code": [None, None],
            "theme_1_level_3_code": [None, None],
            "most_specific_theme_code": [None, None],
        })

        result = adapter._convert_to_news_insert(data)

        assert len(result) == 2
        assert result[0].unique_id == "abc123"
        assert result[0].agency_id == 1
        assert result[0].image_url == "http://img1.jpg"
