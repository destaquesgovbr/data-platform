"""
Unit tests for PostgresManager.

These tests mock the database connection to test logic without requiring a real database.
"""

from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import pytest

from data_platform.managers import PostgresManager
from data_platform.models import News, NewsInsert, Agency, Theme


class TestPostgresManager:
    """Unit tests for PostgresManager."""

    @patch("data_platform.managers.postgres_manager.pool")
    @patch("data_platform.managers.postgres_manager.subprocess")
    def test_init(self, mock_subprocess, mock_pool):
        """Test PostgresManager initialization."""
        # Mock subprocess to return connection string
        mock_subprocess.run.return_value = Mock(
            returncode=0, stdout="postgresql://user:pass@host:5432/db\n"
        )

        manager = PostgresManager(min_connections=2, max_connections=5)

        assert manager.pool is not None
        assert manager._cache_loaded is False
        assert len(manager._agencies_by_key) == 0
        assert len(manager._themes_by_code) == 0

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_agency_by_key(self, mock_pool):
        """Test get_agency_by_key method."""
        manager = PostgresManager(connection_string="postgresql://test")

        # Mock cache
        agency = Agency(id=1, key="mec", name="Ministério da Educação")
        manager._agencies_by_key["mec"] = agency
        manager._cache_loaded = True

        result = manager.get_agency_by_key("mec")

        assert result is not None
        assert result.key == "mec"
        assert result.name == "Ministério da Educação"

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_agency_by_key_not_found(self, mock_pool):
        """Test get_agency_by_key when agency doesn't exist."""
        manager = PostgresManager(connection_string="postgresql://test")
        manager._cache_loaded = True

        result = manager.get_agency_by_key("nonexistent")

        assert result is None

    @patch("data_platform.managers.postgres_manager.pool")
    def test_get_theme_by_code(self, mock_pool):
        """Test get_theme_by_code method."""
        manager = PostgresManager(connection_string="postgresql://test")

        # Mock cache
        theme = Theme(id=1, code="01", label="Economia", level=1)
        manager._themes_by_code["01"] = theme
        manager._cache_loaded = True

        result = manager.get_theme_by_code("01")

        assert result is not None
        assert result.code == "01"
        assert result.label == "Economia"
        assert result.level == 1

    @patch("data_platform.managers.postgres_manager.pool")
    def test_insert_empty_list_raises_error(self, mock_pool):
        """Test that insert raises ValueError on empty list."""
        manager = PostgresManager(connection_string="postgresql://test")

        with pytest.raises(ValueError, match="News list cannot be empty"):
            manager.insert([])

    @patch("data_platform.managers.postgres_manager.pool")
    def test_update_empty_dict_raises_error(self, mock_pool):
        """Test that update raises ValueError on empty updates dict."""
        manager = PostgresManager(connection_string="postgresql://test")

        with pytest.raises(ValueError, match="Updates dictionary cannot be empty"):
            manager.update("unique123", {})

    @patch("data_platform.managers.postgres_manager.pool")
    def test_context_manager(self, mock_pool):
        """Test PostgresManager as context manager."""
        mock_pool_instance = MagicMock()
        mock_pool.SimpleConnectionPool.return_value = mock_pool_instance

        with PostgresManager(connection_string="postgresql://test") as manager:
            assert manager is not None

        # Verify closeall was called
        mock_pool_instance.closeall.assert_called_once()


class TestPostgresManagerConnectionString:
    """Test connection string parsing logic."""

    @patch("data_platform.managers.postgres_manager.subprocess.run")
    @patch("data_platform.managers.postgres_manager.pool")
    def test_connection_string_with_cloud_sql_proxy(self, mock_pool, mock_run):
        """Test connection string when Cloud SQL Proxy is running."""
        # Mock secret manager response
        mock_run.return_value = Mock(
            returncode=0,
            stdout="postgresql://user:pass@10.5.0.3:5432/db\n",
            check=True,
        )

        # Mock pgrep finding cloud-sql-proxy
        with patch(
            "data_platform.managers.postgres_manager.subprocess.run"
        ) as mock_subprocess:

            def run_side_effect(*args, **kwargs):
                if args[0][0] == "pgrep":
                    return Mock(returncode=0)  # Process found
                elif args[0][0] == "gcloud":
                    return Mock(
                        returncode=0, stdout="postgresql://user:pass@10.5.0.3:5432/db\n"
                    )
                return Mock(returncode=1)

            mock_subprocess.side_effect = run_side_effect

            manager = PostgresManager()
            conn_str = manager.connection_string

            # Should use localhost when proxy is detected
            assert "127.0.0.1" in conn_str
            assert "5432" in conn_str


class TestModels:
    """Test Pydantic models."""

    def test_news_model(self):
        """Test News model creation."""
        news = News(
            id=1,
            unique_id="test123",
            agency_id=1,
            title="Test News",
            published_at=datetime(2024, 1, 1),
        )

        assert news.id == 1
        assert news.unique_id == "test123"
        assert news.title == "Test News"

    def test_news_insert_model(self):
        """Test NewsInsert model creation."""
        news = NewsInsert(
            unique_id="test123",
            agency_id=1,
            title="Test News",
            published_at=datetime(2024, 1, 1),
        )

        assert news.unique_id == "test123"
        assert news.title == "Test News"
        # NewsInsert is for insert operations, doesn't need id

    def test_agency_model(self):
        """Test Agency model creation."""
        agency = Agency(id=1, key="mec", name="Ministério da Educação", type="Ministério")

        assert agency.id == 1
        assert agency.key == "mec"
        assert agency.name == "Ministério da Educação"

    def test_theme_model(self):
        """Test Theme model creation."""
        theme = Theme(id=1, code="01", label="Economia", level=1)

        assert theme.id == 1
        assert theme.code == "01"
        assert theme.level == 1

    def test_theme_level_validation(self):
        """Test Theme level validation (must be 1, 2, or 3)."""
        # Valid levels
        Theme(code="01", label="Test", level=1)
        Theme(code="02", label="Test", level=2)
        Theme(code="03", label="Test", level=3)

        # Invalid level should fail validation
        with pytest.raises(Exception):  # Pydantic raises validation error
            Theme(code="04", label="Test", level=4)
