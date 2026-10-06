"""Bronze Writer, caminho GraphQL (inerte enquanto GRAPHQL_API_URL estiver ausente).

Os campos lidos seguem o SDL (`themeL*`) e `publishedAt` (str ISO) vira datetime,
porque `build_gcs_path` particiona por `published_at.strftime(...)`.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from data_platform.workers.bronze_writer.handler import (
    _fetch_full_article_via_graphql,
    handle_bronze_write,
)


def _news_by_id(**overrides):
    article = {
        "uniqueId": "mec-456",
        "title": "Notícia",
        "url": "https://gov.br/mec/456",
        "imageUrl": "https://gov.br/img.jpg",
        "videoUrl": None,
        "content": "Conteúdo.",
        "summary": "Resumo",
        "subtitle": None,
        "editorialLead": None,
        "category": "Educação",
        "tags": ["mec"],
        "agencyKey": "mec",
        "agencyName": "Ministério da Educação",
        "publishedAt": "2025-06-15T10:00:00Z",
        "extractedAt": "2025-06-15T12:00:00+00:00",
        "themeL1Code": "06",
        "themeL1Label": "Educação",
        "themeL2Code": "06.01",
        "themeL2Label": "Ensino Superior",
        "themeL3Code": "06.01.02",
        "themeL3Label": "Bolsas",
        "mostSpecificThemeCode": "06.01.02",
        "mostSpecificThemeLabel": "Bolsas",
        "features": {"word_count": 1},
    }
    article.update(overrides)
    return {"newsById": article}


class TestFetchFullArticleViaGraphql:
    def test_mapeia_themeL(self):
        gql = MagicMock()
        gql.query.return_value = _news_by_id()

        article = _fetch_full_article_via_graphql("mec-456", gql)

        assert article["theme_l1_code"] == "06"
        assert article["theme_l1_label"] == "Educação"
        assert article["theme_l2_code"] == "06.01"
        assert article["theme_l2_label"] == "Ensino Superior"
        assert article["theme_l3_code"] == "06.01.02"
        assert article["theme_l3_label"] == "Bolsas"
        assert article["most_specific_theme_code"] == "06.01.02"
        assert article["most_specific_theme_label"] == "Bolsas"

    def test_datas_viram_datetime_utc(self):
        gql = MagicMock()
        gql.query.return_value = _news_by_id()

        article = _fetch_full_article_via_graphql("mec-456", gql)

        assert article["published_at"] == datetime(2025, 6, 15, 10, 0, tzinfo=UTC)
        assert article["extracted_at"] == datetime(2025, 6, 15, 12, 0, tzinfo=UTC)

    def test_nao_encontrado(self):
        gql = MagicMock()
        gql.query.return_value = {"newsById": None}

        assert _fetch_full_article_via_graphql("x", gql) is None


class TestHandleBronzeWriteGraphql:
    @patch("data_platform.workers.bronze_writer.handler.write_to_gcs")
    @patch.dict("os.environ", {"GCS_BUCKET": "test-bucket"})
    def test_particiona_pelo_published_at_do_graphql(self, mock_write):
        """Sem mock do build_gcs_path: com str dava AttributeError em .strftime."""
        gql = MagicMock()
        gql.query.return_value = _news_by_id(publishedAt="2025-06-15T23:30:00-03:00")
        pg = MagicMock()

        result = handle_bronze_write("mec-456", pg, gql_client=gql)

        assert result == {
            "status": "written",
            "unique_id": "mec-456",
            "gcs_path": "bronze/news/2025/06/16/mec-456.json",
        }
        pg.get_connection.assert_not_called()
        mock_write.assert_called_once()
