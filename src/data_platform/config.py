"""
Centralized configuration management for data-platform.

This module provides a single source of truth for all configuration values,
replacing scattered os.getenv() calls throughout the codebase.

Usage:
    from data_platform.config import get_settings

    settings = get_settings()
    print(settings.database_url)
    print(settings.typesense_host)
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings have sensible defaults for local development.
    Production values should be set via environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # Database Configuration
    # ==========================================================================
    database_url: str = ""

    # ==========================================================================
    # Typesense Configuration
    # ==========================================================================
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_protocol: str = "http"
    typesense_api_key: str = ""
    typesense_connection_timeout_seconds: int = 10

    # ==========================================================================
    # HuggingFace Configuration
    # ==========================================================================
    hf_token: str = ""
    hf_repo_id: str = "destaquesgovbr/govbrnews"

    # ==========================================================================
    # Storage Configuration
    # ==========================================================================
    storage_backend: str = "postgres"  # postgres, huggingface, dual_write
    storage_read_from: str = "postgres"  # postgres, huggingface

    # ==========================================================================
    # Embedding Configuration
    # ==========================================================================
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    embedding_batch_size: int = 32

    # ==========================================================================
    # GCP Configuration
    # ==========================================================================
    gcp_project_id: str = ""
    gcs_bucket: str = ""

    # ==========================================================================
    # Application Configuration
    # ==========================================================================
    log_level: str = "INFO"
    debug: bool = False

    @property
    def typesense_url(self) -> str:
        """Construct full Typesense URL."""
        return f"{self.typesense_protocol}://{self.typesense_host}:{self.typesense_port}"

    @property
    def has_database_url(self) -> bool:
        """Check if database URL is configured."""
        return bool(self.database_url)

    @property
    def has_typesense_api_key(self) -> bool:
        """Check if Typesense API key is configured."""
        return bool(self.typesense_api_key)

    @property
    def has_hf_token(self) -> bool:
        """Check if HuggingFace token is configured."""
        return bool(self.hf_token)


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings.

    Returns the same Settings instance on subsequent calls (cached).
    Use get_settings.cache_clear() to reset the cache if needed.
    """
    return Settings()


def get_fresh_settings() -> Settings:
    """
    Get fresh (non-cached) application settings.

    Useful for testing when you need to reload settings from environment.
    """
    return Settings()
