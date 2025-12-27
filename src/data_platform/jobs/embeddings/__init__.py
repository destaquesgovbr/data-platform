"""
Embeddings module for semantic search.

Phase 4.7: Embeddings Semânticos
"""

from .embedding_generator import EmbeddingGenerator
from .typesense_sync import TypesenseSyncManager

__all__ = ["EmbeddingGenerator", "TypesenseSyncManager"]
