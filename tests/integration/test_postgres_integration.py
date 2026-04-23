"""
Integration tests for PostgresManager.

These tests require a running PostgreSQL database (via Cloud SQL Proxy or local instance).
Run with: pytest tests/integration/ -v
"""

from datetime import UTC, datetime

import pytest

from data_platform.managers import PostgresManager
from data_platform.models import NewsInsert


@pytest.mark.integration
class TestPostgresIntegration:
    """Integration tests for PostgresManager."""

    def test_connection(self, postgres_manager: PostgresManager) -> None:
        """Test database connection works."""
        count = postgres_manager.count()
        assert isinstance(count, int), "Count should return an integer"
        assert count >= 0, "Count should be non-negative"

    def test_cache_loading(self, postgres_manager: PostgresManager) -> None:
        """Test agency and theme cache loading."""
        # Verify agencies loaded
        assert len(postgres_manager._agencies_by_key) > 0
        assert len(postgres_manager._agencies_by_id) > 0

        # Verify themes loaded
        assert len(postgres_manager._themes_by_code) > 0
        assert len(postgres_manager._themes_by_id) > 0

        # Check expected data
        mec = postgres_manager.get_agency_by_key("mec")
        assert mec is not None
        assert "Educação" in mec.name

        theme01 = postgres_manager.get_theme_by_code("01")
        assert theme01 is not None
        assert theme01.level == 1

    def test_insert_and_get(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Test inserting and retrieving news."""
        # Create test news using factory
        test_news = news_factory(title="Test Integration News")
        cleanup_news.append(test_news.unique_id)

        # Insert
        inserted = postgres_manager.insert([test_news])
        assert inserted == 1, "Should insert exactly 1 record"

        # Retrieve
        news = postgres_manager.get_by_unique_id(test_news.unique_id)
        assert news is not None, "Inserted news should be retrievable"
        assert news.title == "Test Integration News"
        assert news.agency_id == test_news.agency_id
        assert news.url == test_news.url
        assert news.content == test_news.content

        # No manual cleanup needed - cleanup_news fixture handles it

    def test_update(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Test updating news."""
        # Create and insert test news
        test_news = news_factory(title="Original Title")
        cleanup_news.append(test_news.unique_id)
        postgres_manager.insert([test_news])

        # Update
        updated = postgres_manager.update(
            test_news.unique_id, {"title": "Updated Title", "summary": "Test summary"}
        )
        assert updated is True, "Update should return True"

        # Verify update
        news = postgres_manager.get_by_unique_id(test_news.unique_id)
        assert news is not None
        assert news.title == "Updated Title"
        assert news.summary == "Test summary"

        # No manual cleanup needed - cleanup_news fixture handles it

    def test_count_with_filters(
        self, postgres_manager: PostgresManager, test_agency
    ) -> None:
        """Test counting with filters."""
        # Get count of all news
        total = postgres_manager.count()
        assert isinstance(total, int), "Count should return an integer"
        assert total >= 0

        # Get count by agency
        count_by_agency = postgres_manager.count({"agency_id": test_agency.id})
        assert isinstance(count_by_agency, int), "Count should return an integer"
        assert count_by_agency <= total, "Agency count should be <= total count"

    def test_insert_duplicate_ignores(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Test that inserting duplicate unique_id is ignored."""
        test_news = news_factory(title="Original")
        cleanup_news.append(test_news.unique_id)

        # First insert
        inserted1 = postgres_manager.insert([test_news])
        assert inserted1 == 1, "First insert should succeed"

        # Second insert (should be ignored)
        inserted2 = postgres_manager.insert([test_news])
        assert inserted2 == 0, "Duplicate insert should be ignored (ON CONFLICT DO NOTHING)"

        # No manual cleanup needed - cleanup_news fixture handles it

    def test_insert_with_allow_update(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Test insert with allow_update=True."""
        # First insert
        test_news1 = news_factory(title="Original")
        cleanup_news.append(test_news1.unique_id)
        postgres_manager.insert([test_news1])

        # Second insert with different title and allow_update=True
        test_news2 = news_factory(
            unique_id=test_news1.unique_id,  # Same unique_id
            title="Updated via Insert",
        )
        inserted = postgres_manager.insert([test_news2], allow_update=True)
        assert inserted == 1, "Insert with allow_update should return 1"

        # Verify update
        news = postgres_manager.get_by_unique_id(test_news1.unique_id)
        assert news is not None
        assert news.title == "Updated via Insert"

        # No manual cleanup needed - cleanup_news fixture handles it
