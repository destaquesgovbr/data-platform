"""
Integration tests for Typesense E2E sync.

Tests the complete roundtrip:
PostgreSQL → get_news_for_typesense → prepare_document → Typesense → search

Critical validation:
- Documents from PostgreSQL can be indexed in Typesense
- Schema compatibility between PostgreSQL output and Typesense schema
- Search returns indexed documents
- Document count matches PostgreSQL count
- Embeddings are preserved (768 dimensions)
"""

import pytest

from data_platform.managers import PostgresManager
from data_platform.typesense.indexer import prepare_document


@pytest.mark.integration
class TestTypesenseE2ESync:
    """Tests for PostgreSQL → Typesense E2E sync."""

    def test_index_document_roundtrip(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """Complete roundtrip: PG → prepare → Typesense → search."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        assert len(df) == 1, "Should have 1 article for today"

        # Prepare document
        row = df.iloc[0]
        document = prepare_document(row)

        # Index in Typesense
        result = typesense_client.collections[typesense_test_collection].documents.upsert(
            document
        )

        # Verify upsert succeeded
        assert "id" in result

        # Search for the document
        search_results = typesense_client.collections[
            typesense_test_collection
        ].documents.search(
            {
                "q": "Today",
                "query_by": "title",
            }
        )

        # Verify document found
        assert search_results["found"] >= 1
        assert len(search_results["hits"]) >= 1

        # Verify document content
        found_doc = search_results["hits"][0]["document"]
        assert found_doc["title"] == "Today's News"
        assert found_doc["agency"] == "mec"

    def test_collection_schema_compatibility(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """PostgreSQL document is accepted by Typesense schema."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        # Prepare document
        row = df.iloc[0]
        document = prepare_document(row)

        # Attempt to index (should not raise schema validation error)
        result = typesense_client.collections[typesense_test_collection].documents.upsert(
            document
        )

        # Verify success
        assert "id" in result
        assert result["id"] == document["id"]

    def test_batch_indexing(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """Batch indexing of multiple documents."""
        # Get all 3 news articles
        df = postgres_manager.get_news_for_typesense(
            start_date=typesense_test_data["dates"]["two_days_ago"],
            end_date=typesense_test_data["dates"]["today"],
        )

        assert len(df) == 3, "Should have 3 articles"

        # Prepare all documents
        documents = [prepare_document(row) for _, row in df.iterrows()]

        # Batch import
        results = typesense_client.collections[typesense_test_collection].documents.import_(
            documents, {"action": "upsert"}
        )

        # Verify all succeeded
        success_count = sum(1 for r in results if r.get("success"))
        assert success_count == 3, f"Expected 3 successes, got {success_count}"

        # Verify count in Typesense
        search_results = typesense_client.collections[
            typesense_test_collection
        ].documents.search(
            {
                "q": "*",  # Match all
                "query_by": "title",
                "per_page": 10,
            }
        )

        assert search_results["found"] == 3

    def test_document_fields_preserved(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """All important fields are preserved in roundtrip."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        row = df.iloc[0]
        document = prepare_document(row)

        # Index
        typesense_client.collections[typesense_test_collection].documents.upsert(document)

        # Retrieve document by ID
        retrieved = typesense_client.collections[typesense_test_collection].documents[
            document["id"]
        ].retrieve()

        # Verify core fields
        assert retrieved["title"] == "Today's News"
        assert retrieved["agency"] == "mec"
        assert retrieved["url"] == "https://example.com/today"
        assert "content" in retrieved

        # Verify theme fields
        assert "theme_1_level_1_code" in retrieved
        assert "theme_1_level_1_label" in retrieved

        # Verify feature fields
        assert "sentiment_label" in retrieved
        assert retrieved["sentiment_label"] == "positive"
        assert "word_count" in retrieved
        assert retrieved["word_count"] == 150

    def test_embeddings_preserved(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """768-dim embedding vectors are preserved."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        row = df.iloc[0]
        document = prepare_document(row)

        # Verify embedding in prepared document
        if "content_embedding" in document and document["content_embedding"]:
            # Should have 768 dimensions
            embedding = document["content_embedding"]
            assert isinstance(embedding, list), "Embedding should be a list"
            assert len(embedding) == 768, f"Expected 768 dims, got {len(embedding)}"

            # Index
            typesense_client.collections[typesense_test_collection].documents.upsert(
                document
            )

            # Retrieve
            retrieved = typesense_client.collections[typesense_test_collection].documents[
                document["id"]
            ].retrieve()

            # Verify embedding preserved
            if "content_embedding" in retrieved:
                retrieved_embedding = retrieved["content_embedding"]
                assert len(retrieved_embedding) == 768
        else:
            pytest.skip("No embedding in document")

    def test_search_by_sentiment(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """Can filter by sentiment (JSONB field from PostgreSQL)."""
        # Get all news
        df = postgres_manager.get_news_for_typesense(
            start_date=typesense_test_data["dates"]["two_days_ago"],
            end_date=typesense_test_data["dates"]["today"],
        )

        # Index all
        documents = [prepare_document(row) for _, row in df.iterrows()]
        typesense_client.collections[typesense_test_collection].documents.import_(
            documents, {"action": "upsert"}
        )

        # Search for positive sentiment only
        search_results = typesense_client.collections[
            typesense_test_collection
        ].documents.search(
            {
                "q": "*",
                "query_by": "title",
                "filter_by": "sentiment_label:positive",
            }
        )

        # Should find exactly 1 (today's news has positive sentiment)
        assert search_results["found"] == 1
        assert search_results["hits"][0]["document"]["title"] == "Today's News"

    def test_update_document(
        self,
        postgres_manager: PostgresManager,
        typesense_client,
        typesense_test_collection: str,
        typesense_test_data: dict,
    ) -> None:
        """Can update existing document (upsert)."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        row = df.iloc[0]
        document = prepare_document(row)

        # First insert
        typesense_client.collections[typesense_test_collection].documents.upsert(document)

        # Modify document
        document["title"] = "Updated Title"

        # Update (upsert again)
        typesense_client.collections[typesense_test_collection].documents.upsert(document)

        # Retrieve
        retrieved = typesense_client.collections[typesense_test_collection].documents[
            document["id"]
        ].retrieve()

        # Verify update
        assert retrieved["title"] == "Updated Title"

        # Verify count is still 1 (not duplicated)
        search_results = typesense_client.collections[
            typesense_test_collection
        ].documents.search({"q": "*", "query_by": "title"})
        assert search_results["found"] == 1


@pytest.mark.integration
class TestTypesenseDocumentPreparation:
    """Tests for prepare_document function."""

    def test_prepare_document_required_fields(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """prepare_document includes all required fields."""
        # Get news from PostgreSQL
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        row = df.iloc[0]
        document = prepare_document(row)

        # Required fields for Typesense
        required_fields = [
            "id",
            "unique_id",
            "agency",
            "title",
            "url",
        ]

        for field in required_fields:
            assert field in document, f"Missing required field: {field}"

        # Should have at least one timestamp field
        has_timestamp = (
            "published_at_ts" in document
            or "published_at" in document
            or "extracted_at" in document
        )
        assert has_timestamp, "Should have at least one timestamp field"

    def test_prepare_document_handles_nulls(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """prepare_document handles NULL fields gracefully."""
        # Create news with minimal data (many NULLs)
        news = news_factory(
            title="Minimal News",
            summary=None,  # NULL
            image_url=None,  # NULL
            video_url=None,  # NULL
        )
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Get from Typesense query
        df = postgres_manager.get_news_for_typesense(
            start_date=news.published_at.date().isoformat()
        )

        matching = df[df["title"] == "Minimal News"]
        assert len(matching) == 1

        row = matching.iloc[0]
        document = prepare_document(row)

        # Should not crash, document should be valid
        assert "id" in document
        assert "title" in document

    def test_prepare_document_array_fields(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """prepare_document handles array fields (tags)."""
        # Get news with tags
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        row = df.iloc[0]
        document = prepare_document(row)

        # Today's news has tags
        if "tags" in document and document["tags"]:
            assert isinstance(document["tags"], list)
            assert len(document["tags"]) > 0
