"""Testes unitários para priorização de verificação de integridade."""

from data_platform.jobs.integrity.priority import (
    CONTENT_CHECK_RATIO,
    PRIORITY_TIERS,
    PRIORITY_QUERY,
)


class TestPriorityTiers:
    """Testes para configuração de tiers de prioridade."""

    def test_tiers_count(self):
        assert len(PRIORITY_TIERS) == 5

    def test_tiers_ordered_by_priority(self):
        tier_numbers = [t[0] for t in PRIORITY_TIERS]
        assert tier_numbers == [1, 2, 3, 4, 5]

    def test_tier_1_is_most_recent(self):
        tier, max_age, recheck, limit = PRIORITY_TIERS[0]
        assert tier == 1
        assert "3 hours" in max_age
        assert "10 minutes" in recheck
        assert limit == 200

    def test_tier_5_is_oldest(self):
        tier, max_age, recheck, limit = PRIORITY_TIERS[4]
        assert tier == 5
        assert "5 months" in max_age
        assert "7 days" in recheck
        assert limit == 20

    def test_batch_limits_decrease_with_age(self):
        limits = [t[3] for t in PRIORITY_TIERS]
        assert limits == sorted(limits, reverse=True)


class TestPriorityQuery:
    """Testes para a query SQL de priorização."""

    def test_query_excludes_old_articles(self):
        query_str = str(PRIORITY_QUERY)
        assert "5 months" in query_str

    def test_query_has_tier_logic(self):
        query_str = str(PRIORITY_QUERY)
        assert "3 hours" in query_str
        assert "24 hours" in query_str
        assert "7 days" in query_str
        assert "30 days" in query_str

    def test_query_orders_by_tier(self):
        query_str = str(PRIORITY_QUERY)
        assert "ORDER BY" in query_str
        assert "tier ASC" in query_str

    def test_query_prioritizes_never_checked(self):
        query_str = str(PRIORITY_QUERY)
        assert "integrity IS NULL" in query_str

    def test_query_uses_batch_size_param(self):
        query_str = str(PRIORITY_QUERY)
        assert ":batch_size" in query_str

    def test_query_selects_required_fields(self):
        query_str = str(PRIORITY_QUERY)
        assert "unique_id" in query_str
        assert "url" in query_str
        assert "image_url" in query_str
        assert "published_at" in query_str


class TestContentCheckRatio:
    """Testes para proporção de checks de conteúdo."""

    def test_ratio_is_reasonable(self):
        assert 0 < CONTENT_CHECK_RATIO <= 1.0

    def test_ratio_is_quarter(self):
        assert CONTENT_CHECK_RATIO == 0.25
