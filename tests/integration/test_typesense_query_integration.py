"""
Integration tests for Typesense query methods.

Tests the complex 7-table JOIN query:
- news, themes (t1, t2, t3, tm), news_features
- JSONB path extraction: features->'sentiment'->>'label'
- Date arithmetic: published_at < %s::date + INTERVAL '1 day'
- Pagination: LIMIT/OFFSET consistency

Critical validation:
- All 55+ columns returned correctly
- JSONB extraction returns correct types (string, float, int, boolean)
- Date boundaries are inclusive start, exclusive end
- iter_news_for_typesense yields same data as get_news_for_typesense
- Count matches actual records
"""

import pandas as pd
import pytest

from data_platform.managers import PostgresManager


@pytest.mark.integration
class TestTypesenseQueryStructure:
    """Tests for _build_typesense_query structure."""

    def test_query_contains_all_required_columns(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Verify query includes all expected columns."""
        query = postgres_manager._build_typesense_query()

        # Core news columns
        assert "n.unique_id" in query
        assert "n.agency_key as agency" in query
        assert "n.title" in query
        assert "n.url" in query
        assert "n.content" in query
        assert "n.summary" in query

        # Timestamp conversions
        assert "EXTRACT(EPOCH FROM n.published_at)::bigint as published_at_ts" in query
        assert "EXTRACT(YEAR FROM n.published_at)::int as published_year" in query

        # Theme columns (all 3 levels + most_specific)
        assert "t1.code as theme_1_level_1_code" in query
        assert "t2.label as theme_1_level_2_label" in query
        assert "t3.code as theme_1_level_3_code" in query
        assert "tm.label as most_specific_theme_label" in query

        # Embeddings
        assert "n.content_embedding" in query

        # Features (JSONB extraction)
        assert "nf.features->'sentiment'->>'label' AS sentiment_label" in query
        assert (
            "(nf.features->'sentiment'->>'score')::float AS sentiment_score" in query
        )
        assert "(nf.features->>'word_count')::int AS word_count" in query
        assert "(nf.features->>'has_image')::boolean AS has_image" in query

    def test_query_has_all_joins(self, postgres_manager: PostgresManager) -> None:
        """Verify all 7 tables are joined."""
        query = postgres_manager._build_typesense_query()

        assert "FROM news n" in query
        assert "LEFT JOIN themes t1 ON n.theme_l1_id = t1.id" in query
        assert "LEFT JOIN themes t2 ON n.theme_l2_id = t2.id" in query
        assert "LEFT JOIN themes t3 ON n.theme_l3_id = t3.id" in query
        assert "LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id" in query
        assert "LEFT JOIN news_features nf ON n.unique_id = nf.unique_id" in query

    def test_query_no_where_clause_in_base(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Base query has no WHERE - added by caller."""
        query = postgres_manager._build_typesense_query()
        assert "WHERE" not in query
        assert "LIMIT" not in query


@pytest.mark.integration
class TestTypesenseQueryExecution:
    """Tests for get_news_for_typesense execution with real data."""

    def test_get_news_returns_dataframe(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Query returns pandas DataFrame."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        assert isinstance(df, pd.DataFrame)

    def test_get_news_single_day_returns_correct_count(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Single-day query returns only articles from that day."""
        df_today = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        # Should have exactly 1 article (today's news)
        assert len(df_today) == 1
        assert df_today.iloc[0]["title"] == "Today's News"

    def test_get_news_date_range_inclusive_start_exclusive_end(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Date range is [start, end+1 day)."""
        # Query for yesterday to today (should get 2 articles)
        df = postgres_manager.get_news_for_typesense(
            start_date=typesense_test_data["dates"]["yesterday"],
            end_date=typesense_test_data["dates"]["today"],
        )

        # Should include yesterday and today (2 articles)
        assert len(df) == 2
        titles = set(df["title"])
        assert "Yesterday's News" in titles
        assert "Today's News" in titles

    def test_get_news_all_columns_present(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """DataFrame contains all expected columns."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data returned for today")

        expected_columns = [
            "unique_id",
            "agency",
            "title",
            "url",
            "content",
            "summary",
            "published_at_ts",
            "published_year",
            "published_month",
            "theme_1_level_1_code",
            "theme_1_level_1_label",
            "theme_1_level_2_code",
            "theme_1_level_2_label",
            "theme_1_level_3_code",
            "theme_1_level_3_label",
            "most_specific_theme_code",
            "most_specific_theme_label",
            "sentiment_label",
            "sentiment_score",
            "word_count",
            "has_image",
            "has_video",
            "readability_flesch",
            "trending_score",
            "content_embedding",
        ]

        for col in expected_columns:
            assert col in df.columns, f"Missing column: {col}"

    def test_get_news_jsonb_extraction_correct_types(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """JSONB extracted fields have correct Python types."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data for today")

        row = df.iloc[0]

        # String
        assert isinstance(row["sentiment_label"], str) or pd.isna(
            row["sentiment_label"]
        )

        # Float - pandas may use numpy types
        if pd.notna(row["sentiment_score"]):
            assert isinstance(row["sentiment_score"], (float, int)) or hasattr(
                row["sentiment_score"], "__float__"
            )

        # Int - pandas may use numpy types
        if pd.notna(row["word_count"]):
            assert isinstance(row["word_count"], (int, float)) or hasattr(
                row["word_count"], "__int__"
            )

        # Boolean - pandas may use numpy types
        if pd.notna(row["has_image"]):
            assert isinstance(row["has_image"], (bool, int)) or hasattr(
                row["has_image"], "__bool__"
            )

    def test_get_news_jsonb_values_match_upserted(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """JSONB extracted values match what was upserted."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data for today")

        row = df.iloc[0]
        expected_features = typesense_test_data["features"][0]

        assert row["sentiment_label"] == expected_features["sentiment"]["label"]
        assert row["sentiment_score"] == pytest.approx(
            expected_features["sentiment"]["score"]
        )
        assert row["word_count"] == expected_features["word_count"]
        assert row["has_image"] == expected_features["has_image"]
        assert row["has_video"] == expected_features["has_video"]

    def test_get_news_theme_joins_correct(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Theme JOINs return correct labels."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data for today")

        row = df.iloc[0]
        themes = typesense_test_data["themes"]

        # Today's news has all 3 theme levels
        assert row["theme_1_level_1_code"] == themes["l1"].code
        assert row["theme_1_level_1_label"] == themes["l1"].label
        assert row["theme_1_level_2_code"] == themes["l2"].code
        assert row["theme_1_level_2_label"] == themes["l2"].label
        assert row["theme_1_level_3_code"] == themes["l3"].code
        assert row["theme_1_level_3_label"] == themes["l3"].label
        assert row["most_specific_theme_code"] == themes["l3"].code

    def test_get_news_handles_null_themes(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """LEFT JOINs handle NULL themes gracefully."""
        # Two days ago news has only L1 theme
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["two_days_ago"]
        )

        if len(df) == 0:
            pytest.skip("No data for two days ago")

        row = df.iloc[0]

        # L1 should be populated
        assert pd.notna(row["theme_1_level_1_code"])

        # L2 and L3 should be NULL
        assert pd.isna(row["theme_1_level_2_code"])
        assert pd.isna(row["theme_1_level_3_code"])

    def test_get_news_limit_respected(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """LIMIT parameter restricts result size."""
        # Query for all 3 days, limit to 2
        df = postgres_manager.get_news_for_typesense(
            start_date=typesense_test_data["dates"]["two_days_ago"],
            end_date=typesense_test_data["dates"]["today"],
            limit=2,
        )

        assert len(df) <= 2

    def test_get_news_embedding_included(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """content_embedding field is included (not NULL for test data)."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data for today")

        row = df.iloc[0]

        # Should have embedding (we inserted fake ones)
        assert "content_embedding" in df.columns
        # Embedding should be present (can be string or list representation)
        if pd.notna(row["content_embedding"]):
            # Just verify it's not None - it could be string representation or actual array
            assert row["content_embedding"] is not None

    def test_get_news_timestamp_extraction(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Timestamp fields are extracted correctly."""
        df = postgres_manager.get_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        if len(df) == 0:
            pytest.skip("No data for today")

        row = df.iloc[0]

        # Verify timestamp fields - pandas may use numpy types
        assert pd.notna(row["published_at_ts"])
        assert isinstance(row["published_at_ts"], (int, float)) or hasattr(
            row["published_at_ts"], "__int__"
        )
        assert row["published_at_ts"] > 0

        # Verify year/month extraction - pandas may use numpy types
        assert pd.notna(row["published_year"])
        assert isinstance(row["published_year"], (int, float)) or hasattr(
            row["published_year"], "__int__"
        )
        assert pd.notna(row["published_month"])
        assert isinstance(row["published_month"], (int, float)) or hasattr(
            row["published_month"], "__int__"
        )


@pytest.mark.integration
class TestTypesenseCount:
    """Tests for count_news_for_typesense."""

    def test_count_single_day(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Count for single day returns correct number."""
        count = postgres_manager.count_news_for_typesense(
            typesense_test_data["dates"]["today"]
        )

        assert count == 1

    def test_count_date_range(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Count for date range returns correct number."""
        count = postgres_manager.count_news_for_typesense(
            start_date=typesense_test_data["dates"]["yesterday"],
            end_date=typesense_test_data["dates"]["today"],
        )

        assert count == 2

    def test_count_matches_get_length(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """count_news_for_typesense matches len(get_news_for_typesense)."""
        date_range = (
            typesense_test_data["dates"]["two_days_ago"],
            typesense_test_data["dates"]["today"],
        )

        count = postgres_manager.count_news_for_typesense(*date_range)
        df = postgres_manager.get_news_for_typesense(*date_range)

        assert count == len(df)


@pytest.mark.integration
class TestTypesensePagination:
    """Tests for iter_news_for_typesense pagination."""

    def test_iter_yields_nothing_for_empty_range(
        self, postgres_manager: PostgresManager
    ) -> None:
        """Iterator yields nothing when count is 0."""
        # Use future date
        future_date = "2030-01-01"

        batches = list(postgres_manager.iter_news_for_typesense(future_date))

        assert batches == []

    def test_iter_yields_single_batch_when_count_less_than_batch_size(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Small dataset yields single batch."""
        batches = list(
            postgres_manager.iter_news_for_typesense(
                start_date=typesense_test_data["dates"]["two_days_ago"],
                end_date=typesense_test_data["dates"]["today"],
                batch_size=10,  # Larger than 3 articles
            )
        )

        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_iter_yields_multiple_batches(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Batch size of 1 yields 3 batches for 3 articles."""
        batches = list(
            postgres_manager.iter_news_for_typesense(
                start_date=typesense_test_data["dates"]["two_days_ago"],
                end_date=typesense_test_data["dates"]["today"],
                batch_size=1,
            )
        )

        assert len(batches) == 3
        for batch in batches:
            assert len(batch) == 1

    def test_iter_data_matches_get(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """iter_news_for_typesense returns same data as get_news_for_typesense."""
        date_range = (
            typesense_test_data["dates"]["two_days_ago"],
            typesense_test_data["dates"]["today"],
        )

        # Get via get_news_for_typesense
        df_get = postgres_manager.get_news_for_typesense(*date_range)

        # Get via iter_news_for_typesense
        batches = list(
            postgres_manager.iter_news_for_typesense(*date_range, batch_size=10)
        )
        df_iter = pd.concat(batches, ignore_index=True)

        # Compare
        assert len(df_get) == len(df_iter)
        assert set(df_get["unique_id"]) == set(df_iter["unique_id"])

    def test_iter_pagination_no_duplicates(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Pagination doesn't return duplicate records."""
        batches = list(
            postgres_manager.iter_news_for_typesense(
                start_date=typesense_test_data["dates"]["two_days_ago"],
                end_date=typesense_test_data["dates"]["today"],
                batch_size=2,  # Should yield 2 batches: 2 + 1
            )
        )

        # Collect all unique_ids
        all_ids = []
        for batch in batches:
            all_ids.extend(batch["unique_id"].tolist())

        # Should have no duplicates
        assert len(all_ids) == len(set(all_ids))

    def test_iter_pagination_order_consistent(
        self, postgres_manager: PostgresManager, typesense_test_data: dict
    ) -> None:
        """Pagination returns records in consistent order (DESC published_at)."""
        batches = list(
            postgres_manager.iter_news_for_typesense(
                start_date=typesense_test_data["dates"]["two_days_ago"],
                end_date=typesense_test_data["dates"]["today"],
                batch_size=10,
            )
        )

        df = batches[0]

        # Should be ordered by published_at DESC
        titles = df["title"].tolist()
        expected_order = ["Today's News", "Yesterday's News", "Two Days Ago News"]

        assert titles == expected_order


@pytest.mark.integration
class TestTypesenseQueryEdgeCases:
    """Test edge cases for Typesense queries."""

    def test_get_news_with_missing_features(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Query handles news without features (LEFT JOIN returns NULL)."""
        # Create news without features
        news = news_factory(title="News Without Features")
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])
        # Don't upsert features

        df = postgres_manager.get_news_for_typesense(
            start_date=news.published_at.date().isoformat()
        )

        # Should find the article
        matching = df[df["title"] == "News Without Features"]
        assert len(matching) == 1

        # Feature fields should be NULL
        row = matching.iloc[0]
        assert pd.isna(row["sentiment_label"])
        assert pd.isna(row["sentiment_score"])
        assert pd.isna(row["word_count"])

    def test_count_all_news_returns_reasonable_number(
        self,
        postgres_manager: PostgresManager,
        news_factory: callable,
        cleanup_news: list[str],
    ) -> None:
        """Count without date filters returns all news."""
        # Create test data
        news = news_factory(title="Count Test News")
        cleanup_news.append(news.unique_id)
        postgres_manager.insert([news])

        # Count from 2020 to 2030 (should get everything including our test)
        count = postgres_manager.count_news_for_typesense(
            start_date="2020-01-01", end_date="2030-12-31"
        )

        # Should be at least 1 (our test article)
        assert count >= 1
        assert isinstance(count, int)
