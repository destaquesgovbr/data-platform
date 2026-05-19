"""Testes unitários para priorização de verificação de integridade."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from data_platform.jobs.integrity.priority import (
    ALLOWED_URL_PREFIXES,
    CONTENT_CHECK_RATIO,
    PRIORITY_TIERS,
    PRIORITY_QUERY,
    _is_allowed_url,
    fetch_priority_batch,
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


class TestIsAllowedUrl:
    """Testes para a funcao de validacao de URL."""

    def test_none_is_allowed(self):
        assert _is_allowed_url(None) is True

    def test_empty_string_is_allowed(self):
        assert _is_allowed_url("") is True

    def test_gov_br_is_allowed(self):
        assert _is_allowed_url("https://www.gov.br/mec/pt-br/imagem.jpg") is True

    def test_ebc_is_allowed(self):
        assert _is_allowed_url("https://agenciabrasil.ebc.com.br/img.jpg") is True

    def test_imagens_ebc_is_allowed(self):
        assert _is_allowed_url("https://imagens.ebc.com.br/photo.jpg") is True

    def test_staticflickr_is_allowed(self):
        assert _is_allowed_url("https://live.staticflickr.com/123/img.jpg") is True

    def test_gcs_thumbnails_is_allowed(self):
        assert _is_allowed_url("https://storage.googleapis.com/destaquesgovbr-thumbnails/x.jpg") is True

    def test_random_domain_is_rejected(self):
        assert _is_allowed_url("https://cdn.example.com/img.jpg") is False

    def test_http_gov_br_is_rejected(self):
        assert _is_allowed_url("http://www.gov.br/img.jpg") is False

    def test_gov_br_without_www_is_rejected(self):
        assert _is_allowed_url("https://gov.br/img.jpg") is False

    def test_other_gcs_bucket_is_rejected(self):
        assert _is_allowed_url("https://storage.googleapis.com/other-bucket/x.jpg") is False


def _make_row(unique_id="art-1", url="https://www.gov.br/mec/noticia",
              image_url="https://www.gov.br/mec/img.jpg", published_at=None,
              integrity=None):
    """Cria um mock de row do SQLAlchemy."""
    row = MagicMock()
    row.unique_id = unique_id
    row.url = url
    row.image_url = image_url
    row.published_at = published_at
    row.integrity = integrity
    return row


@pytest.fixture
def mock_db():
    """Mock do engine e conexao SQLAlchemy."""
    with patch("data_platform.jobs.integrity.priority.create_engine") as mock_engine_cls:
        mock_engine = MagicMock()
        mock_engine_cls.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_conn, mock_engine


class TestFetchPriorityBatchUrlFiltering:
    """Testes para filtragem de URLs fora da allowlist."""

    def test_filters_disallowed_image_url(self, mock_db):
        mock_conn, _ = mock_db
        row = _make_row(image_url="https://cdn.example.com/photo.jpg")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        articles = fetch_priority_batch("postgresql://test", batch_size=10)

        assert len(articles) == 1
        assert articles[0]["image_url"] is None

    def test_keeps_allowed_image_url(self, mock_db):
        mock_conn, _ = mock_db
        expected_url = "https://www.gov.br/mec/pt-br/imagem.jpg"
        row = _make_row(image_url=expected_url)
        mock_conn.execute.return_value.fetchall.return_value = [row]

        articles = fetch_priority_batch("postgresql://test", batch_size=10)

        assert articles[0]["image_url"] == expected_url

    def test_none_image_url_stays_none(self, mock_db):
        mock_conn, _ = mock_db
        row = _make_row(image_url=None)
        mock_conn.execute.return_value.fetchall.return_value = [row]

        articles = fetch_priority_batch("postgresql://test", batch_size=10)

        assert articles[0]["image_url"] is None

    def test_logs_filtered_urls(self, mock_db, caplog):
        mock_conn, _ = mock_db
        row = _make_row(image_url="https://cdn.example.com/photo.jpg")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        with caplog.at_level(logging.WARNING):
            fetch_priority_batch("postgresql://test", batch_size=10)

        assert any("image_url filtrada" in msg for msg in caplog.messages)

    def test_filters_disallowed_article_url(self, mock_db):
        mock_conn, _ = mock_db
        row = _make_row(url="https://external-site.org/news/123")
        mock_conn.execute.return_value.fetchall.return_value = [row]

        articles = fetch_priority_batch("postgresql://test", batch_size=10)

        assert articles[0]["url"] is None

    def test_keeps_allowed_article_url(self, mock_db):
        mock_conn, _ = mock_db
        expected_url = "https://www.gov.br/mec/pt-br/noticias/artigo"
        row = _make_row(url=expected_url)
        mock_conn.execute.return_value.fetchall.return_value = [row]

        articles = fetch_priority_batch("postgresql://test", batch_size=10)

        assert articles[0]["url"] == expected_url

    def test_summary_log_with_filtered_count(self, mock_db, caplog):
        mock_conn, _ = mock_db
        rows = [
            _make_row(unique_id="a1", image_url="https://cdn.x.com/1.jpg"),
            _make_row(unique_id="a2", image_url="https://www.gov.br/ok.jpg"),
            _make_row(unique_id="a3", image_url="https://evil.org/x.jpg"),
        ]
        mock_conn.execute.return_value.fetchall.return_value = rows

        with caplog.at_level(logging.WARNING):
            fetch_priority_batch("postgresql://test", batch_size=10)

        assert any("2/3" in msg and "allowlist" in msg for msg in caplog.messages)
