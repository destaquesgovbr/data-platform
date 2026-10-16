"""
Unit tests for feature_worker handler.

Tests handle_feature_computation() orchestration:
- fetch article → compute features → upsert
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from data_platform.workers.feature_worker.handler import handle_feature_computation


@pytest.fixture
def mock_pg():
    pg = MagicMock()
    pg.get_connection.return_value = MagicMock()
    pg.put_connection = MagicMock()
    pg.upsert_features = MagicMock(return_value=True)
    return pg


# The PG fetch query returns 8 columns:
#   unique_id, content, image_url, video_url, published_at,
#   entities, annotations_source_hash, has_content_annotations
_ROW_WIDTH = 8


def _make_cursor(row=None):
    cursor = MagicMock()
    # Pad shorter test rows with None for the trailing annotation-skip columns
    # (annotations_source_hash, has_content_annotations) so callers can keep
    # passing the core fields only.
    if row is not None and len(row) < _ROW_WIDTH:
        row = (*row, *([None] * (_ROW_WIDTH - len(row))))
    cursor.fetchone.return_value = row
    cursor.close = MagicMock()
    return cursor


class TestHandleFeatureComputation:
    def test_returns_computed_status_for_existing_article(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Conteúdo do artigo com várias palavras para teste.",
                "https://example.com/img.jpg",
                None,
                datetime(2024, 6, 17, 14, 0, 0, tzinfo=UTC),
                None,  # entities
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["status"] == "computed"
        assert result["unique_id"] == "abc123"
        assert isinstance(result["features"], list)
        assert "word_count" in result["features"]
        assert "has_image" in result["features"]
        assert "content_annotations" in result["features"]
        assert "annotations_source_hash" in result["features"]

    def test_returns_not_found_for_missing_article(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=None)
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("nonexistent", mock_pg)

        assert result["status"] == "not_found"
        assert result["unique_id"] == "nonexistent"
        mock_pg.upsert_features.assert_not_called()

    def test_calls_upsert_features_with_computed_dict(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Texto com conteúdo para feature computation.",
                None,
                None,
                datetime(2024, 6, 17, 9, 0, 0),
                None,
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        mock_pg.upsert_features.assert_called_once()
        call_args = mock_pg.upsert_features.call_args
        unique_id_arg = call_args[0][0]
        features_arg = call_args[0][1]

        assert unique_id_arg == "abc123"
        assert isinstance(features_arg, dict)
        assert features_arg["word_count"] > 0
        assert features_arg["has_image"] is False

    def test_propagates_upsert_error(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1), None))
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn
        mock_pg.upsert_features.side_effect = Exception("DB error during upsert")

        with pytest.raises(Exception, match="DB error during upsert"):
            handle_feature_computation("abc123", mock_pg)

    def test_connection_returned_to_pool_on_success(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=("abc123", "Conteúdo.", None, None, datetime(2024, 1, 1), None))
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        mock_pg.put_connection.assert_called_once_with(conn)

    def test_connection_returned_to_pool_when_not_found(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=None)
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("missing", mock_pg)

        mock_pg.put_connection.assert_called_once_with(conn)

    def test_features_include_publication_fields_when_published_at_set(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Texto de artigo.",
                None,
                None,
                datetime(2024, 6, 17, 14, 30, 0, tzinfo=UTC),
                None,
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "publication_hour" in features_arg
        assert features_arg["publication_hour"] == 14
        assert "publication_dow" in features_arg

    def test_features_omit_publication_fields_when_published_at_none(self, mock_pg):
        conn = MagicMock()
        cursor = _make_cursor(row=("abc123", "Texto de artigo.", None, None, None, None))
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "publication_hour" not in features_arg
        assert "publication_dow" not in features_arg

    def test_content_annotations_derived_from_entities(self, mock_pg):
        """Existing entities in news_features yield inline offsets in the upsert."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "O MEC anunciou novidades hoje cedo de manhã.",
                None,
                None,
                datetime(2024, 1, 1),
                [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}],
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        anns = features_arg["content_annotations"]
        assert anns == [
            {"start": 2, "end": 5, "type": "ORG", "text": "MEC", "canonical_id": "dgb_mec"}
        ]
        assert isinstance(features_arg["annotations_source_hash"], str)

    def test_content_annotations_empty_when_entities_absent(self, mock_pg):
        """No entities (race with enrichment worker) → empty annotations, no crash."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=("abc123", "Texto sem entidades.", None, None, datetime(2024, 1, 1), None)
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["status"] == "computed"
        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert features_arg["content_annotations"] == []

    def test_content_annotations_from_json_string_entities(self, mock_pg):
        """Entities arriving as a JSON-encoded string (driver variance) still parse."""
        import json

        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "Lula discursou em Brasília.",
                None,
                None,
                datetime(2024, 1, 1),
                json.dumps([{"text": "Lula", "type": "PER", "canonical_id": "Q8765"}]),
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        anns = features_arg["content_annotations"]
        assert len(anns) == 1
        assert anns[0]["text"] == "Lula"
        assert anns[0]["canonical_id"] == "Q8765"

    def test_upsert_merges_without_dropping_other_keys(self, mock_pg):
        """The handler passes a feature dict; upsert_features merges via JSONB || so
        other pre-existing keys (e.g. entities, sentiment) are preserved upstream.
        Here we assert the handler does not overwrite the whole features object —
        it only adds the keys it computed (incl. content_annotations)."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "O MEC agiu.",
                None,
                None,
                datetime(2024, 1, 1),
                [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}],
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        handle_feature_computation("abc123", mock_pg)

        features_arg = mock_pg.upsert_features.call_args[0][1]
        # The handler must NOT include `entities` in its upsert payload (it only
        # reads them), so the existing entities are never clobbered by the merge.
        assert "entities" not in features_arg
        assert "content_annotations" in features_arg
        assert "word_count" in features_arg

    def test_annotations_recompute_skipped_when_hash_unchanged(self, mock_pg):
        """When stored hash matches AND content_annotations exists, the annotation
        derivation is skipped (not re-written), but other features still upsert."""
        from data_platform.workers.feature_worker.features import (
            compute_annotations_source_hash,
        )

        content = "O MEC agiu."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}]
        stored_hash = compute_annotations_source_hash(content, entities)

        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                content,
                None,
                None,
                datetime(2024, 1, 1),
                entities,
                stored_hash,  # annotations_source_hash matches
                True,  # has_content_annotations
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["annotations_skipped"] is True
        features_arg = mock_pg.upsert_features.call_args[0][1]
        # Skipped → neither annotation key is in the upsert payload …
        assert "content_annotations" not in features_arg
        assert "annotations_source_hash" not in features_arg
        # … but the cheap content-driven features are still recomputed.
        assert "word_count" in features_arg

    def test_annotations_recompute_runs_when_hash_changes(self, mock_pg):
        """A stale stored hash (entities changed) forces recompute of annotations."""
        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                "O MEC agiu.",
                None,
                None,
                datetime(2024, 1, 1),
                [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}],
                "stale-hash-does-not-match",
                True,
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["annotations_skipped"] is False
        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert features_arg["content_annotations"] == [
            {"start": 2, "end": 5, "type": "ORG", "text": "MEC", "canonical_id": "dgb_mec"}
        ]
        assert "annotations_source_hash" in features_arg

    def test_annotations_recompute_runs_when_key_absent_even_if_hash_matches(self, mock_pg):
        """Hash matches but content_annotations key is missing → must recompute
        (guards against a hash written without the annotations list)."""
        from data_platform.workers.feature_worker.features import (
            compute_annotations_source_hash,
        )

        content = "O MEC agiu."
        entities = [{"text": "MEC", "type": "ORG", "canonical_id": "dgb_mec"}]
        stored_hash = compute_annotations_source_hash(content, entities)

        conn = MagicMock()
        cursor = _make_cursor(
            row=(
                "abc123",
                content,
                None,
                None,
                datetime(2024, 1, 1),
                entities,
                stored_hash,
                False,  # content_annotations key NOT present
            )
        )
        conn.cursor.return_value = cursor
        mock_pg.get_connection.return_value = conn

        result = handle_feature_computation("abc123", mock_pg)

        assert result["annotations_skipped"] is False
        features_arg = mock_pg.upsert_features.call_args[0][1]
        assert "content_annotations" in features_arg


# =============================================================================
# Caminho GraphQL (inerte enquanto GRAPHQL_API_URL estiver ausente; DP-A)
# =============================================================================


def _graphql_news_by_id(**overrides):
    """Resposta de newsById com os campos que NEWS_BY_ID_QUERY seleciona."""
    article = {
        "uniqueId": "abc123",
        "title": "Título",
        "url": "https://gov.br/abc123",
        "imageUrl": "https://gov.br/img.jpg",
        "videoUrl": None,
        "content": "Conteúdo do artigo com várias palavras para o teste do caminho GraphQL.",
        "summary": None,
        "subtitle": None,
        "editorialLead": None,
        "category": None,
        "tags": [],
        "agencyKey": "mec",
        "agencyName": "Ministério da Educação",
        "publishedAt": "2024-06-17T14:30:00Z",
        "extractedAt": "2024-06-17T15:00:00Z",
        "themeL1Code": "06",
        "themeL1Label": "Educação",
        "themeL2Code": None,
        "themeL2Label": None,
        "themeL3Code": None,
        "themeL3Label": None,
        "mostSpecificThemeCode": "06",
        "mostSpecificThemeLabel": "Educação",
        "features": {"sentiment": {"label": "neutral", "score": 0.5}},
    }
    article.update(overrides)
    return {"newsById": article}


class TestHandleFeatureComputationGraphql:
    def test_graphql_published_at_string_gera_publication_hour(self, mock_pg):
        """publishedAt chega como str ISO ('Z'); antes dava AttributeError em .hour."""
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id(publishedAt="2024-06-17T14:30:00Z")

        result = handle_feature_computation("abc123", mock_pg, gql_client=gql)

        assert result["status"] == "computed"
        features = gql.mutate.call_args[0][1]["features"]
        assert features["publication_hour"] == 14
        assert features["publication_dow"] == 0  # segunda-feira

    def test_graphql_published_at_com_offset_normaliza_para_utc(self, mock_pg):
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id(publishedAt="2024-06-17T11:30:00-03:00")

        handle_feature_computation("abc123", mock_pg, gql_client=gql)

        features = gql.mutate.call_args[0][1]["features"]
        assert features["publication_hour"] == 14

    def test_graphql_published_at_nulo_omite_campos_de_publicacao(self, mock_pg):
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id(publishedAt=None)

        handle_feature_computation("abc123", mock_pg, gql_client=gql)

        features = gql.mutate.call_args[0][1]["features"]
        assert "publication_hour" not in features

    def test_upsert_graphql_envia_dict(self, mock_pg):
        """O escalar JSON recebe o objeto; json.dumps virava jsonb string → array no merge."""
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id()

        handle_feature_computation("abc123", mock_pg, gql_client=gql)

        variables = gql.mutate.call_args[0][1]
        assert variables["uniqueId"] == "abc123"
        assert isinstance(variables["features"], dict)
        assert variables["features"]["word_count"] > 0
        mock_pg.upsert_features.assert_not_called()

    def test_graphql_usa_entities_do_blob_features(self, mock_pg):
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id(
            content="O Ministério da Educação anunciou hoje um novo programa nacional amplo.",
            features={"entities": [{"text": "Ministério da Educação", "type": "ORG", "count": 1}]},
        )

        handle_feature_computation("abc123", mock_pg, gql_client=gql)

        annotations = gql.mutate.call_args[0][1]["features"]["content_annotations"]
        assert [a["text"] for a in annotations] == ["Ministério da Educação"]


class TestHandleFeatureComputationGraphqlFeaturesComoString:
    """No `newsById`, o `features` chega como str JSON (asyncpg sem codec de JSONB).

    Tratar a str como `{}` descartava entities, annotations_source_hash e a
    chave content_annotations: o worker mandava `content_annotations: []` e o
    merge `features || $2::jsonb` da API apagava as anotações gravadas.
    """

    CONTENT = "O Ministério da Educação anunciou hoje um novo programa nacional amplo."
    ENTITIES = [{"text": "Ministério da Educação", "type": "ORG", "count": 1}]

    def _gql(self, blob: dict):
        gql = MagicMock()
        gql.query.return_value = _graphql_news_by_id(
            content=self.CONTENT, features=json.dumps(blob, ensure_ascii=False)
        )
        return gql

    def test_entities_da_string_geram_anotacoes(self, mock_pg):
        gql = self._gql({"entities": self.ENTITIES})

        result = handle_feature_computation("abc123", mock_pg, gql_client=gql)

        assert result["annotations_skipped"] is False
        annotations = gql.mutate.call_args[0][1]["features"]["content_annotations"]
        assert [a["text"] for a in annotations] == ["Ministério da Educação"]

    def test_hash_igual_na_string_pula_e_nao_sobrescreve_anotacoes(self, mock_pg):
        from data_platform.workers.feature_worker.features import (
            compute_annotations_source_hash,
        )

        blob = {
            "entities": self.ENTITIES,
            "content_annotations": [{"x": 1}],
            "annotations_source_hash": compute_annotations_source_hash(self.CONTENT, self.ENTITIES),
        }
        gql = self._gql(blob)

        result = handle_feature_computation("abc123", mock_pg, gql_client=gql)

        assert result["annotations_skipped"] is True
        sent = gql.mutate.call_args[0][1]["features"]
        assert "content_annotations" not in sent
        assert "annotations_source_hash" not in sent

    def test_fetch_le_hash_e_presenca_das_anotacoes_da_string(self):
        from data_platform.workers.feature_worker.handler import _fetch_article_via_graphql

        gql = self._gql(
            {
                "entities": self.ENTITIES,
                "content_annotations": [],
                "annotations_source_hash": "abc",
            }
        )

        article = _fetch_article_via_graphql("abc123", gql)

        assert article["entities"] == self.ENTITIES
        assert article["existing_annotations_hash"] == "abc"
        assert article["has_content_annotations"] is True
