"""
Shared fixtures for integration tests.

This conftest provides:
- Database connection fixtures (session and function scoped)
- Test data factories for news, agencies, themes
- Cleanup utilities
"""

import os
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from data_platform.managers import PostgresManager
from data_platform.models import Agency, NewsInsert, Theme

# Use Docker PostgreSQL by default
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev",
)


# -------------------------------------------------------------------------
# Environment Setup
# -------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def env_vars() -> Generator[None, None, None]:
    """Configure environment variables for all integration tests."""
    original_env = os.environ.copy()

    os.environ.update(
        {
            "DATABASE_URL": DATABASE_URL,
            "TESTING": "1",
        }
    )

    yield

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# -------------------------------------------------------------------------
# PostgresManager Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_manager_session(env_vars: None) -> Generator[PostgresManager, None, None]:
    """
    Session-scoped PostgresManager for master data (agencies, themes).

    Use this for read-only operations that don't modify data.
    """
    try:
        manager = PostgresManager()
        manager.load_cache()
        yield manager
        manager.close_all()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


@pytest.fixture(scope="function")
def postgres_manager(env_vars: None) -> Generator[PostgresManager, None, None]:
    """
    Function-scoped PostgresManager for write operations.

    Use this for tests that insert/update/delete data.
    Each test gets a fresh manager instance.
    """
    try:
        manager = PostgresManager()
        manager.load_cache()
        yield manager
        manager.close_all()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


# -------------------------------------------------------------------------
# Master Data Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_agency(postgres_manager_session: PostgresManager) -> Agency:
    """Get MEC agency for testing (read-only)."""
    agency = postgres_manager_session.get_agency_by_key("mec")
    if not agency:
        pytest.skip("MEC agency not found - run 'make populate-master'")
    return agency


@pytest.fixture(scope="session")
def test_theme(postgres_manager_session: PostgresManager) -> Theme:
    """Get a level-1 theme for testing (read-only)."""
    theme = postgres_manager_session.get_theme_by_code("01")
    if not theme:
        pytest.skip("Theme '01' not found - run 'make populate-master'")
    return theme


# -------------------------------------------------------------------------
# Test Data Factories
# -------------------------------------------------------------------------


@pytest.fixture
def news_factory(test_agency: Agency) -> callable:
    """
    Factory for generating test news records with unique IDs.

    Usage:
        news = news_factory(title="Custom Title")
        news_batch = [news_factory() for _ in range(10)]
    """
    counter = 0

    def _make_news(**overrides: Any) -> NewsInsert:
        nonlocal counter
        counter += 1
        timestamp = datetime.now(UTC).timestamp()

        defaults = {
            "unique_id": f"test_news_{timestamp}_{counter}",
            "agency_id": test_agency.id,
            "agency_key": test_agency.key,
            "agency_name": test_agency.name,
            "title": f"Test News {counter}",
            "url": f"https://example.com/test/{counter}",
            "content": f"Test content {counter}" * 20,  # ~300 chars
            "published_at": datetime.now(UTC) - timedelta(days=counter),
            "extracted_at": datetime.now(UTC),
        }
        defaults.update(overrides)
        return NewsInsert(**defaults)

    return _make_news


@pytest.fixture
def cleanup_news(postgres_manager: PostgresManager) -> Generator[list[str], None, None]:
    """
    Track news unique_ids for cleanup after test.

    Usage:
        def test_something(cleanup_news):
            cleanup_news.append("test_id_1")
            # ... test code ...
            # cleanup happens automatically
    """
    unique_ids: list[str] = []
    yield unique_ids

    # Cleanup: DELETE records (not soft-delete)
    if unique_ids:
        conn = postgres_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM news WHERE unique_id = ANY(%s)",
                    (unique_ids,),
                )
                deleted = cur.rowcount
                conn.commit()
                if deleted > 0:
                    print(f"\nCleaned up {deleted} test records")
        except Exception as e:
            conn.rollback()
            print(f"\nWarning: cleanup failed: {e}")
        finally:
            postgres_manager.put_connection(conn)


# -------------------------------------------------------------------------
# Date Helpers
# -------------------------------------------------------------------------


@pytest.fixture
def date_ranges() -> dict[str, str]:
    """Common date ranges for testing."""
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    last_week = today - timedelta(days=7)

    return {
        "today": today.isoformat(),
        "yesterday": yesterday.isoformat(),
        "last_week": last_week.isoformat(),
    }


# -------------------------------------------------------------------------
# Typesense Query Test Data
# -------------------------------------------------------------------------


@pytest.fixture
def typesense_test_data(
    postgres_manager: PostgresManager,
    test_agency: Agency,
    cleanup_news: list[str],
) -> dict[str, Any]:
    """
    Create comprehensive test data for Typesense query validation.

    Creates:
    - 3 news articles with different dates
    - Theme assignments (L1, L2, L3)
    - Features with sentiment, word_count, etc.
    - Embeddings (fake 768-dim vectors)

    Returns dict with created data for assertions.
    """
    # Get themes from cache
    theme_l1 = postgres_manager.get_theme_by_code("02")  # Educação
    theme_l2 = postgres_manager.get_theme_by_code("02.01")  # Ensino Básico
    theme_l3 = postgres_manager.get_theme_by_code("02.01.01")  # Educação Infantil

    if not all([theme_l1, theme_l2, theme_l3]):
        pytest.skip("Required themes not found - run 'make populate-master'")

    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # Create 3 news articles with different characteristics
    news_records = [
        NewsInsert(
            unique_id=f"ts_test_today_{datetime.now(UTC).timestamp()}",
            agency_id=test_agency.id,
            agency_key=test_agency.key,
            agency_name=test_agency.name,
            title="Today's News",
            url="https://example.com/today",
            content="Content for today's news article",
            summary="Summary of today's news",
            published_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
            extracted_at=datetime.now(UTC),
            theme_l1_id=theme_l1.id,
            theme_l2_id=theme_l2.id,
            theme_l3_id=theme_l3.id,
            most_specific_theme_id=theme_l3.id,
            image_url="https://example.com/image1.jpg",
            video_url=None,
            category="Notícia",
            tags=["educação", "infantil"],
            content_embedding=[0.1] * 768,  # Fake 768-dim vector
        ),
        NewsInsert(
            unique_id=f"ts_test_yesterday_{datetime.now(UTC).timestamp()}",
            agency_id=test_agency.id,
            agency_key=test_agency.key,
            agency_name=test_agency.name,
            title="Yesterday's News",
            url="https://example.com/yesterday",
            content="Content for yesterday's news article",
            published_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC),
            extracted_at=datetime.now(UTC),
            theme_l1_id=theme_l1.id,
            theme_l2_id=theme_l2.id,
            most_specific_theme_id=theme_l2.id,  # No L3
            image_url=None,
            video_url="https://example.com/video1.mp4",
            content_embedding=[0.2] * 768,
        ),
        NewsInsert(
            unique_id=f"ts_test_two_days_{datetime.now(UTC).timestamp()}",
            agency_id=test_agency.id,
            agency_key=test_agency.key,
            agency_name=test_agency.name,
            title="Two Days Ago News",
            url="https://example.com/two_days",
            content="Content for two days ago news article",
            published_at=datetime.combine(
                two_days_ago, datetime.min.time(), tzinfo=UTC
            ),
            extracted_at=datetime.now(UTC),
            theme_l1_id=theme_l1.id,
            most_specific_theme_id=theme_l1.id,  # Only L1
        ),
    ]

    # Insert news
    for news in news_records:
        cleanup_news.append(news.unique_id)
    postgres_manager.insert(news_records)

    # Add features for each article
    features_data = [
        {
            "sentiment": {"label": "positive", "score": 0.8},
            "trending_score": 0.9,
            "word_count": 150,
            "has_image": True,
            "has_video": False,
            "readability_flesch": 65.5,
        },
        {
            "sentiment": {"label": "neutral", "score": 0.5},
            "trending_score": 0.4,
            "word_count": 200,
            "has_image": False,
            "has_video": True,
            "readability_flesch": 55.3,
        },
        {
            "sentiment": {"label": "negative", "score": 0.3},
            "trending_score": 0.2,
            "word_count": 100,
            "has_image": False,
            "has_video": False,
            "readability_flesch": 70.1,
        },
    ]

    for news, features in zip(news_records, features_data):
        postgres_manager.upsert_features(news.unique_id, features)

    return {
        "news": news_records,
        "features": features_data,
        "dates": {
            "today": today.isoformat(),
            "yesterday": yesterday.isoformat(),
            "two_days_ago": two_days_ago.isoformat(),
        },
        "themes": {
            "l1": theme_l1,
            "l2": theme_l2,
            "l3": theme_l3,
        },
    }


# -------------------------------------------------------------------------
# Typesense E2E Test Fixtures
# -------------------------------------------------------------------------


@pytest.fixture(scope="session")
def typesense_client():
    """
    Session-scoped Typesense client for E2E tests.

    Uses Docker Typesense on port 8108.
    Skip if Typesense not available.
    """
    try:
        from data_platform.typesense.client import get_client

        client = get_client()

        # Test connection
        client.collections.retrieve()

        yield client
    except Exception as e:
        pytest.skip(f"Typesense not available: {e}")


@pytest.fixture
def typesense_test_collection(typesense_client) -> Generator[str, None, None]:
    """
    Function-scoped test collection.

    Creates a temporary collection for testing, deletes after test.
    """
    from data_platform.typesense.collection import COLLECTION_SCHEMA

    collection_name = f"test_collection_{datetime.now(UTC).timestamp()}"

    # Create test collection (modify schema name)
    test_schema = COLLECTION_SCHEMA.copy()
    test_schema["name"] = collection_name

    try:
        typesense_client.collections.create(test_schema)
        yield collection_name
    finally:
        # Cleanup: delete collection
        try:
            typesense_client.collections[collection_name].delete()
        except Exception as e:
            print(f"\nWarning: Failed to delete test collection: {e}")
