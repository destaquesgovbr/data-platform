"""
Tests for centralized configuration management.

These tests ensure that:
1. Settings load correctly from environment variables
2. Default values work properly
3. The caching mechanism works as expected
4. Properties are computed correctly
"""

import os
from unittest.mock import patch

import pytest


class TestSettingsDefaults:
    """Tests for default configuration values."""

    def test_settings_has_defaults(self):
        """Testa valores default das configurações."""
        # Use fresh settings to avoid cache issues
        from data_platform.config import Settings

        # Clear any existing env vars that might interfere
        env_vars_to_clear = [
            "DATABASE_URL",
            "TYPESENSE_HOST",
            "TYPESENSE_PORT",
            "TYPESENSE_API_KEY",
            "HF_TOKEN",
            "STORAGE_BACKEND",
            "STORAGE_READ_FROM",
        ]

        # Create a clean environment with only cleared vars
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars_to_clear}

        with patch.dict(os.environ, clean_env, clear=True):
            settings = Settings()

            assert settings.typesense_host == "localhost"
            assert settings.typesense_port == 8108
            assert settings.typesense_protocol == "http"
            assert settings.database_url == ""
            assert settings.hf_repo_id == "destaquesgovbr/govbrnews"
            assert settings.storage_backend == "postgres"

    def test_settings_log_level_default(self):
        """Testa default do log level."""
        from data_platform.config import Settings

        settings = Settings()
        assert settings.log_level == "INFO"
        assert settings.debug is False


class TestSettingsFromEnv:
    """Tests for loading settings from environment variables."""

    def test_settings_loads_from_env(self):
        """Testa carregamento de configurações de variáveis de ambiente."""
        from data_platform.config import Settings

        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test:test@localhost/testdb",
                "TYPESENSE_HOST": "typesense.example.com",
                "TYPESENSE_PORT": "9108",
                "TYPESENSE_API_KEY": "test-api-key-123",
                "HF_TOKEN": "hf_test_token",
            },
        ):
            settings = Settings()

            assert settings.database_url == "postgresql://test:test@localhost/testdb"
            assert settings.typesense_host == "typesense.example.com"
            assert settings.typesense_port == 9108
            assert settings.typesense_api_key == "test-api-key-123"
            assert settings.hf_token == "hf_test_token"

    def test_settings_case_insensitive(self):
        """Testa que as variáveis de ambiente são case-insensitive."""
        from data_platform.config import Settings

        # Pydantic settings should handle both cases
        with patch.dict(
            os.environ,
            {
                "typesense_host": "lowercase-host.com",
            },
        ):
            settings = Settings()
            assert settings.typesense_host == "lowercase-host.com"

    def test_settings_partial_override(self):
        """Testa override parcial de configurações."""
        from data_platform.config import Settings

        with patch.dict(
            os.environ,
            {
                "TYPESENSE_HOST": "custom-host.com",
                # PORT not set, should use default
            },
        ):
            settings = Settings()
            assert settings.typesense_host == "custom-host.com"
            assert settings.typesense_port == 8108  # Default


class TestSettingsCaching:
    """Tests for the settings caching mechanism."""

    def test_get_settings_is_cached(self):
        """Testa que get_settings() retorna a mesma instância (cached)."""
        from data_platform.config import get_settings

        # Clear cache first
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2

    def test_get_fresh_settings_not_cached(self):
        """Testa que get_fresh_settings() retorna nova instância."""
        from data_platform.config import get_fresh_settings

        settings1 = get_fresh_settings()
        settings2 = get_fresh_settings()

        # Should be equal but not the same object
        assert settings1 is not settings2
        assert settings1.typesense_host == settings2.typesense_host

    def test_cache_clear_works(self):
        """Testa que cache_clear() funciona."""
        from data_platform.config import get_settings

        get_settings.cache_clear()

        with patch.dict(os.environ, {"TYPESENSE_HOST": "first-host.com"}):
            settings1 = get_settings()
            assert settings1.typesense_host == "first-host.com"

        # Clear cache and change env
        get_settings.cache_clear()

        with patch.dict(os.environ, {"TYPESENSE_HOST": "second-host.com"}):
            settings2 = get_settings()
            # After cache clear, should pick up new value
            assert settings2.typesense_host == "second-host.com"


class TestSettingsProperties:
    """Tests for computed properties."""

    def test_typesense_url_property(self):
        """Testa propriedade typesense_url."""
        from data_platform.config import Settings

        with patch.dict(
            os.environ,
            {
                "TYPESENSE_HOST": "ts.example.com",
                "TYPESENSE_PORT": "443",
                "TYPESENSE_PROTOCOL": "https",
            },
        ):
            settings = Settings()
            assert settings.typesense_url == "https://ts.example.com:443"

    def test_has_database_url_property(self):
        """Testa propriedade has_database_url."""
        from data_platform.config import Settings

        # Without DATABASE_URL
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATABASE_URL", None)
            settings = Settings()
            assert settings.has_database_url is False

        # With DATABASE_URL
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://localhost/db"}):
            settings = Settings()
            assert settings.has_database_url is True

    def test_has_typesense_api_key_property(self):
        """Testa propriedade has_typesense_api_key."""
        from data_platform.config import Settings

        # Without API key
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TYPESENSE_API_KEY", None)
            settings = Settings()
            assert settings.has_typesense_api_key is False

        # With API key
        with patch.dict(os.environ, {"TYPESENSE_API_KEY": "some-key"}):
            settings = Settings()
            assert settings.has_typesense_api_key is True

    def test_has_hf_token_property(self):
        """Testa propriedade has_hf_token."""
        from data_platform.config import Settings

        # Without HF token
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HF_TOKEN", None)
            settings = Settings()
            assert settings.has_hf_token is False

        # With HF token
        with patch.dict(os.environ, {"HF_TOKEN": "hf_xxxxx"}):
            settings = Settings()
            assert settings.has_hf_token is True


class TestStorageSettings:
    """Tests for storage-related settings."""

    def test_storage_backend_default(self):
        """Testa default do storage backend."""
        from data_platform.config import Settings

        # Clear storage-related env vars
        env_vars_to_clear = ["STORAGE_BACKEND", "STORAGE_READ_FROM"]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars_to_clear}

        with patch.dict(os.environ, clean_env, clear=True):
            settings = Settings()
            assert settings.storage_backend == "postgres"
            assert settings.storage_read_from == "postgres"

    def test_storage_backend_from_env(self):
        """Testa configuração de storage backend via env."""
        from data_platform.config import Settings

        with patch.dict(
            os.environ,
            {
                "STORAGE_BACKEND": "dual_write",
                "STORAGE_READ_FROM": "huggingface",
            },
        ):
            settings = Settings()
            assert settings.storage_backend == "dual_write"
            assert settings.storage_read_from == "huggingface"


class TestEmbeddingSettings:
    """Tests for embedding-related settings."""

    def test_embedding_defaults(self):
        """Testa defaults das configurações de embedding."""
        from data_platform.config import Settings

        settings = Settings()
        assert "paraphrase-multilingual" in settings.embedding_model
        assert settings.embedding_batch_size == 32

    def test_embedding_from_env(self):
        """Testa configuração de embedding via env."""
        from data_platform.config import Settings

        with patch.dict(
            os.environ,
            {
                "EMBEDDING_MODEL": "custom/model",
                "EMBEDDING_BATCH_SIZE": "64",
            },
        ):
            settings = Settings()
            assert settings.embedding_model == "custom/model"
            assert settings.embedding_batch_size == 64
