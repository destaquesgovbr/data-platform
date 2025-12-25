"""
Integration tests for PostgresManager.

These tests require a running PostgreSQL database (via Cloud SQL Proxy or local instance).
Run with: pytest tests/integration/ -v
"""

from datetime import datetime, timezone
import pytest

from data_platform.managers import PostgresManager
from data_platform.models import NewsInsert


@pytest.fixture(scope="module")
def postgres_manager():
    """Create PostgresManager instance for integration tests."""
    try:
        manager = PostgresManager()
        manager.load_cache()
        yield manager
        manager.close_all()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


class TestPostgresIntegration:
    """Integration tests for PostgresManager."""

    def test_connection(self, postgres_manager):
        """Test database connection works."""
        count = postgres_manager.count()
        assert count >= 0  # Should return a valid count

    def test_cache_loading(self, postgres_manager):
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

    def test_insert_and_get(self, postgres_manager):
        """Test inserting and retrieving news."""
        # Get an agency for testing
        agency = postgres_manager.get_agency_by_key("mec")
        assert agency is not None

        # Create test news
        test_news = NewsInsert(
            unique_id=f"test_{datetime.now().timestamp()}",
            agency_id=agency.id,
            title="Test Integration News",
            url="https://example.com/test",
            content="Test content for integration testing",
            published_at=datetime.now(timezone.utc),
            extracted_at=datetime.now(timezone.utc),
            agency_key="mec",
            agency_name=agency.name,
        )

        # Insert
        inserted = postgres_manager.insert([test_news])
        assert inserted == 1

        # Retrieve
        news = postgres_manager.get_by_unique_id(test_news.unique_id)
        assert news is not None
        assert news.title == "Test Integration News"
        assert news.agency_id == agency.id

        # Clean up
        postgres_manager.update(
            test_news.unique_id, {"title": "DELETED - Integration Test"}
        )

    def test_update(self, postgres_manager):
        """Test updating news."""
        # Get an agency for testing
        agency = postgres_manager.get_agency_by_key("mec")
        assert agency is not None

        # Create and insert test news
        unique_id = f"test_update_{datetime.now().timestamp()}"
        test_news = NewsInsert(
            unique_id=unique_id,
            agency_id=agency.id,
            title="Original Title",
            published_at=datetime.now(timezone.utc),
            agency_key="mec",
            agency_name=agency.name,
        )

        postgres_manager.insert([test_news])

        # Update
        updated = postgres_manager.update(
            unique_id, {"title": "Updated Title", "summary": "Test summary"}
        )
        assert updated is True

        # Verify update
        news = postgres_manager.get_by_unique_id(unique_id)
        assert news.title == "Updated Title"
        assert news.summary == "Test summary"

        # Clean up
        postgres_manager.update(unique_id, {"title": "DELETED - Integration Test"})

    def test_count_with_filters(self, postgres_manager):
        """Test counting with filters."""
        # Get count of all news
        total = postgres_manager.count()
        assert total >= 0

        # Get count by agency
        agency = postgres_manager.get_agency_by_key("mec")
        if agency:
            count_by_agency = postgres_manager.count({"agency_id": agency.id})
            assert count_by_agency >= 0

    def test_insert_duplicate_ignores(self, postgres_manager):
        """Test that inserting duplicate unique_id is ignored."""
        agency = postgres_manager.get_agency_by_key("mec")
        unique_id = f"test_dup_{datetime.now().timestamp()}"

        test_news = NewsInsert(
            unique_id=unique_id,
            agency_id=agency.id,
            title="Original",
            published_at=datetime.now(timezone.utc),
            agency_key="mec",
            agency_name=agency.name,
        )

        # First insert
        inserted1 = postgres_manager.insert([test_news])
        assert inserted1 == 1

        # Second insert (should be ignored)
        inserted2 = postgres_manager.insert([test_news])
        assert inserted2 == 0  # ON CONFLICT DO NOTHING

        # Clean up
        postgres_manager.update(unique_id, {"title": "DELETED - Integration Test"})

    def test_insert_with_allow_update(self, postgres_manager):
        """Test insert with allow_update=True."""
        agency = postgres_manager.get_agency_by_key("mec")
        unique_id = f"test_upd_{datetime.now().timestamp()}"

        # First insert
        test_news1 = NewsInsert(
            unique_id=unique_id,
            agency_id=agency.id,
            title="Original",
            published_at=datetime.now(timezone.utc),
            agency_key="mec",
            agency_name=agency.name,
        )
        postgres_manager.insert([test_news1])

        # Second insert with different title and allow_update=True
        test_news2 = NewsInsert(
            unique_id=unique_id,
            agency_id=agency.id,
            title="Updated via Insert",
            published_at=datetime.now(timezone.utc),
            agency_key="mec",
            agency_name=agency.name,
        )
        inserted = postgres_manager.insert([test_news2], allow_update=True)
        assert inserted == 1

        # Verify update
        news = postgres_manager.get_by_unique_id(unique_id)
        assert news.title == "Updated via Insert"

        # Clean up
        postgres_manager.update(unique_id, {"title": "DELETED - Integration Test"})
