"""
Funções utilitárias para Typesense.
"""

import pandas as pd


def calculate_published_week(timestamp: int | float | None) -> int | None:
    """
    Calcula a semana ISO 8601 no formato YYYYWW a partir de um Unix timestamp.

    Args:
        timestamp: Unix timestamp em segundos

    Returns:
        int no formato YYYYWW (ex: 202543 para semana 43 de 2025)
        Retorna None se o timestamp for inválido

    Examples:
        >>> calculate_published_week(1704110400)  # 2024-01-01
        202401  # Semana 1 de 2024

        >>> calculate_published_week(1729641600)  # 2025-10-23
        202543  # Semana 43 de 2025
    """
    if pd.isna(timestamp) or timestamp is None or timestamp <= 0:
        return None

    try:
        dt = pd.to_datetime(timestamp, unit="s")
        iso_year, iso_week, _ = dt.isocalendar()
        return int(iso_year * 100 + iso_week)
    except Exception:
        return None
