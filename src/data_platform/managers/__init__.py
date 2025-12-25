"""Storage managers for DestaquesGovBr."""

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.managers.storage_adapter import StorageAdapter, StorageBackend

__all__ = ["PostgresManager", "StorageAdapter", "StorageBackend"]
