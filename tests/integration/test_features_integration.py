"""
Integration tests for PostgresManager Feature Store methods.

Tests JSONB merge behavior (|| operator), nested structures, batch queries,
and foreign key constraints with real PostgreSQL database.

Critical validation:
- JSONB || operator preserves existing keys
- JSONB || operator overwrites duplicate keys
- Foreign key to news(unique_id) enforced
- Batch queries handle missing IDs correctly
- CASCADE delete behavior
"""

import pytest

from data_platform.managers import PostgresManager


@pytest.mark.integration
class TestFeatureStoreUpsert:
    """Tests for upsert_features with real PostgreSQL."""

    def test_upsert_creates_new_row(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """First upsert for a unique_id creates a new row."""
        # Setup: Insert a news article
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Act: Upsert features
        result = postgres_manager.upsert_features(news.unique_id, {"word_count": 150})

        # Assert
        assert result is True, "Upsert should return True for new row"

        # Verify features stored
        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["word_count"] == 150

    def test_upsert_merges_features_preserves_existing(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """JSONB || operator preserves existing keys when merging."""
        # Setup
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # First upsert: word_count + sentiment
        postgres_manager.upsert_features(
            news.unique_id,
            {"word_count": 150, "sentiment": {"label": "positive", "score": 0.8}},
        )

        # Second upsert: has_image (should preserve word_count and sentiment)
        postgres_manager.upsert_features(news.unique_id, {"has_image": True})

        # Verify: All keys present
        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["word_count"] == 150, "Existing key should be preserved"
        assert (
            features["sentiment"]["label"] == "positive"
        ), "Nested key preserved"
        assert features["has_image"] is True, "New key added"

    def test_upsert_merges_features_overwrites_duplicates(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """JSONB || operator overwrites duplicate keys."""
        # Setup
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # First upsert
        postgres_manager.upsert_features(
            news.unique_id, {"word_count": 150, "trending_score": 0.5}
        )

        # Second upsert: overwrite trending_score
        postgres_manager.upsert_features(news.unique_id, {"trending_score": 0.9})

        # Verify
        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["word_count"] == 150, "Other key preserved"
        assert features["trending_score"] == 0.9, "Duplicate key overwritten"

    def test_upsert_nested_jsonb_structures(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Complex nested JSONB structures are stored correctly."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Complex nested structure
        complex_features = {
            "sentiment": {
                "label": "neutral",
                "score": 0.5,
                "details": {"positive": 0.3, "negative": 0.2, "neutral": 0.5},
            },
            "entities": [
                {"type": "PERSON", "name": "João Silva"},
                {"type": "ORG", "name": "Ministério"},
            ],
            "metadata": {"version": "1.0", "model": "sentiment-v2"},
        }

        postgres_manager.upsert_features(news.unique_id, complex_features)

        # Verify
        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["sentiment"]["details"]["neutral"] == 0.5
        assert len(features["entities"]) == 2
        assert features["entities"][0]["type"] == "PERSON"
        assert features["metadata"]["version"] == "1.0"

    def test_upsert_foreign_key_constraint_enforced(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Cannot upsert features for non-existent news article."""
        fake_unique_id = "nonexistent_article_123"

        # Attempt to upsert features for non-existent article
        with pytest.raises(Exception) as exc_info:
            postgres_manager.upsert_features(fake_unique_id, {"word_count": 100})

        # Should be a foreign key violation
        error_message = str(exc_info.value).lower()
        assert (
            "foreign key" in error_message or "constraint" in error_message
        ), f"Expected FK error, got: {error_message}"

    def test_upsert_empty_dict_returns_false(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Empty features dict is a no-op."""
        result = postgres_manager.upsert_features("any_id", {})
        assert result is False, "Empty dict should return False"

    def test_upsert_updates_timestamp(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Trigger auto-updates updated_at timestamp on upsert."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # First upsert
        postgres_manager.upsert_features(news.unique_id, {"word_count": 100})

        # Get timestamp
        conn = postgres_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT updated_at FROM news_features WHERE unique_id = %s",
                    (news.unique_id,),
                )
                first_timestamp = cur.fetchone()[0]
        finally:
            postgres_manager.put_connection(conn)

        # Second upsert (should trigger updated_at update)
        postgres_manager.upsert_features(news.unique_id, {"word_count": 200})

        # Get new timestamp
        conn = postgres_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT updated_at FROM news_features WHERE unique_id = %s",
                    (news.unique_id,),
                )
                second_timestamp = cur.fetchone()[0]
        finally:
            postgres_manager.put_connection(conn)

        # Verify timestamp changed
        assert (
            second_timestamp >= first_timestamp
        ), "updated_at should be updated on upsert"


@pytest.mark.integration
class TestFeatureStoreGet:
    """Tests for get_features with real PostgreSQL."""

    def test_get_features_existing(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Retrieve features for an article that has them."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        postgres_manager.upsert_features(
            news.unique_id, {"word_count": 200, "has_image": True}
        )

        features = postgres_manager.get_features(news.unique_id)

        assert features is not None
        assert features["word_count"] == 200
        assert features["has_image"] is True

    def test_get_features_nonexistent_article(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Returns None for non-existent article."""
        features = postgres_manager.get_features("nonexistent_123")
        assert features is None

    def test_get_features_article_without_features(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Returns None for article that exists but has no features."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Don't upsert any features
        features = postgres_manager.get_features(news.unique_id)

        assert features is None, "Should return None when no features row exists"


@pytest.mark.integration
class TestFeatureStoreBatch:
    """Tests for get_features_batch with real PostgreSQL."""

    def test_get_features_batch_all_exist(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Batch get for articles that all have features."""
        # Create 3 articles with features
        articles = [news_factory() for _ in range(3)]
        for i, news in enumerate(articles):
            cleanup_news.append(news.unique_id)
            postgres_manager.insert([news])
            postgres_manager.upsert_features(news.unique_id, {"word_count": 100 + i})

        # Batch get
        unique_ids = [n.unique_id for n in articles]
        result = postgres_manager.get_features_batch(unique_ids)

        # Verify
        assert len(result) == 3
        for i, news in enumerate(articles):
            assert news.unique_id in result
            assert result[news.unique_id]["word_count"] == 100 + i

    def test_get_features_batch_partial(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Batch get with some IDs missing - returns only existing."""
        # Create 2 articles, only 1 with features
        news1 = news_factory()
        news2 = news_factory()
        cleanup_news.extend([news1.unique_id, news2.unique_id])

        postgres_manager.insert([news1, news2])
        postgres_manager.upsert_features(news1.unique_id, {"word_count": 50})
        # news2 has no features

        # Request 3 IDs (1 with features, 1 without, 1 nonexistent)
        result = postgres_manager.get_features_batch(
            [news1.unique_id, news2.unique_id, "nonexistent_999"]
        )

        # Only news1 should be in result
        assert len(result) == 1
        assert news1.unique_id in result
        assert news2.unique_id not in result
        assert "nonexistent_999" not in result

    def test_get_features_batch_empty_list(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Empty input list returns empty dict."""
        result = postgres_manager.get_features_batch([])
        assert result == {}

    def test_get_features_batch_none_exist(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Batch get with no matching IDs returns empty dict."""
        result = postgres_manager.get_features_batch(["fake1", "fake2", "fake3"])
        assert result == {}


@pytest.mark.integration
class TestFeatureStoreCascadeDelete:
    """Test foreign key CASCADE behavior."""

    def test_delete_news_cascades_to_features(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Deleting news article should cascade delete features."""
        news = news_factory()
        cleanup_news.append(news.unique_id)

        # Insert news and features
        postgres_manager.insert([news])
        postgres_manager.upsert_features(news.unique_id, {"word_count": 123})

        # Verify features exist
        features_before = postgres_manager.get_features(news.unique_id)
        assert features_before is not None

        # Delete news article
        conn = postgres_manager.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM news WHERE unique_id = %s", (news.unique_id,)
                )
                conn.commit()
        finally:
            postgres_manager.put_connection(conn)

        # Verify features were cascade deleted
        features_after = postgres_manager.get_features(news.unique_id)
        assert features_after is None, "Features should be cascade deleted"


@pytest.mark.integration
class TestFeatureStoreEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_upsert_features_with_null_values(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """JSONB can store None/null values."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Upsert with None value
        postgres_manager.upsert_features(
            news.unique_id, {"nullable_field": None, "present_field": "value"}
        )

        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["nullable_field"] is None
        assert features["present_field"] == "value"

    def test_upsert_features_with_special_characters(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """JSONB handles special characters correctly."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        special_text = 'Text with "quotes", \'apostrophes\', and émojis 🎉'
        postgres_manager.upsert_features(news.unique_id, {"text": special_text})

        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["text"] == special_text

    def test_upsert_features_with_numeric_types(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """JSONB preserves numeric types correctly."""
        news = news_factory()
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        postgres_manager.upsert_features(
            news.unique_id,
            {
                "int_value": 42,
                "float_value": 3.14159,
                "large_int": 9007199254740991,  # Max safe JS integer
                "small_float": 0.000001,
            },
        )

        features = postgres_manager.get_features(news.unique_id)
        assert features is not None
        assert features["int_value"] == 42
        assert abs(features["float_value"] - 3.14159) < 0.00001
        assert features["large_int"] == 9007199254740991
        assert abs(features["small_float"] - 0.000001) < 0.0000001
