"""
Funções utilitárias para Typesense.

NOTA: Este módulo re-exporta funções de data_platform.utils.datetime_utils
para manter compatibilidade com código existente.
"""

# Re-export from centralized datetime utils for backwards compatibility
from data_platform.utils.datetime_utils import calculate_published_week

__all__ = ["calculate_published_week"]
