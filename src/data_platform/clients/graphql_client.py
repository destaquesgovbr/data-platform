"""
GraphQL client for internal API calls from workers and DAGs.

Uses httpx for HTTP + google-auth for Cloud Run OIDC authentication.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_API_URL = os.environ.get("GRAPHQL_API_URL", "http://localhost:8000/graphql")
GRAPHQL_PATH = "/graphql"


def normalize_graphql_url(url: str) -> str:
    """Acrescenta ``/graphql`` a uma URL sem path.

    O ``.uri`` do Cloud Run (usado como GRAPHQL_API_URL no Terraform) não tem path,
    e a graphql-api só responde em ``/graphql``: um POST na raiz dá 404.
    """
    parts = urlsplit(url)
    if parts.path in ("", "/"):
        return urlunsplit(parts._replace(path=GRAPHQL_PATH))
    return url


def coerce_json_object(value: Any) -> dict[str, Any]:
    """Valor do escalar ``JSON`` da graphql-api → dict.

    No ``newsById``, a API repassa ``news_features.features`` cru do asyncpg, que
    não registra codec de JSONB: o escalar ``JSON`` entrega uma str. Os
    mapeadores de ``newsForTypesense``/``newsBatchForBigquery`` já devolvem o
    objeto. Str JSON de objeto vira dict; dict passa; ausente, JSON inválido ou
    JSON que não é objeto (``null``, array, texto) vira ``{}``.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def oidc_audience(url: str, audience: str | None = None) -> str:
    """Audience do token OIDC: explícito, ``GRAPHQL_API_AUDIENCE`` ou a origem da URL."""
    explicit = audience or os.environ.get("GRAPHQL_API_AUDIENCE")
    if explicit:
        return explicit
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@dataclass
class GraphQLResponse:
    data: dict[str, Any]
    errors: list[dict] | None = None

    @property
    def has_errors(self) -> bool:
        return self.errors is not None and len(self.errors) > 0


class GraphQLClient:
    """
    Synchronous GraphQL client for use in workers and DAGs.

    Uses Google OIDC tokens for authentication when running on Cloud Run.
    Falls back to unauthenticated requests for local development.
    """

    def __init__(
        self,
        url: str | None = None,
        timeout: float = 30.0,
        audience: str | None = None,
    ):
        self.url = normalize_graphql_url(url or GRAPHQL_API_URL)
        self.audience = oidc_audience(self.url, audience)
        self.timeout = timeout
        self._http_client = httpx.Client(timeout=timeout)

    def _get_auth_headers(self) -> dict[str, str]:
        """Get OIDC token for Cloud Run service-to-service auth."""
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            auth_request = google.auth.transport.requests.Request()
            token = google.oauth2.id_token.fetch_id_token(auth_request, self.audience)
            return {"Authorization": f"Bearer {token}"}
        except Exception as e:
            logger.debug(f"OIDC token not available (local dev?): {e}")
            return {}

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> GraphQLResponse:
        """
        Execute a GraphQL query or mutation.

        Args:
            query: GraphQL query/mutation string
            variables: Optional variables dict

        Returns:
            GraphQLResponse with data and optional errors
        """
        headers = {"Content-Type": "application/json"}
        headers.update(self._get_auth_headers())

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self._http_client.post(
            self.url,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        result = response.json()

        return GraphQLResponse(
            data=result.get("data", {}),
            errors=result.get("errors"),
        )

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a query and return data. Raises on errors."""
        resp = self.execute(query, variables)
        if resp.has_errors:
            error_msgs = "; ".join(e.get("message", "Unknown") for e in resp.errors)
            raise GraphQLError(f"GraphQL errors: {error_msgs}")
        return resp.data

    def mutate(self, mutation: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a mutation and return data. Raises on errors."""
        return self.query(mutation, variables)

    def close(self):
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class GraphQLError(Exception):
    """Raised when a GraphQL request returns errors."""

    pass


# --- GraphQL Query/Mutation Templates ---
# Validados contra o SDL da graphql-api em tests/unit/clients/test_graphql_contract.py
# (snapshot em tests/fixtures/graphql_api_schema.graphql). O schema não tem o
# escalar `ID`: identificadores são `String!`.

NEWS_BY_ID_QUERY = """
query NewsById($uniqueId: String!) {
  newsById(uniqueId: $uniqueId) {
    uniqueId title url imageUrl videoUrl content summary subtitle
    editorialLead category tags agencyKey agencyName
    publishedAt extractedAt
    themeL1Code themeL1Label themeL2Code themeL2Label
    themeL3Code themeL3Label mostSpecificThemeCode mostSpecificThemeLabel
    features
  }
}
"""

NEWS_FOR_TYPESENSE_QUERY = """
query NewsForTypesense($uniqueId: String!) {
  newsForTypesense(uniqueId: $uniqueId) {
    uniqueId title url imageUrl videoUrl content summary subtitle
    editorialLead category tags agencyKey agencyName
    publishedAt extractedAt
    themeL1Code themeL1Label themeL2Code themeL2Label
    themeL3Code themeL3Label mostSpecificThemeCode mostSpecificThemeLabel
    contentEmbedding sentimentLabel sentimentScore
    trendingScore wordCount hasImage hasVideo imageBroken readabilityFlesch
    features
  }
}
"""

# char_count, paragraph_count, publication_hour e publication_dow não existem em
# BigQueryRecordType: saem do blob `features` (ver sync_to_bigquery).
NEWS_BATCH_FOR_BIGQUERY_QUERY = """
query NewsBatchForBigquery($startDate: String!, $endDate: String!, $batchSize: Int, $cursor: String) {
  newsBatchForBigquery(startDate: $startDate, endDate: $endDate, batchSize: $batchSize, cursor: $cursor) {
    uniqueId title url agencyKey agencyName publishedAt extractedAt
    themeL1Code themeL1Label themeL2Code themeL2Label
    mostSpecificThemeCode mostSpecificThemeLabel
    wordCount hasImage hasVideo
    sentimentLabel sentimentScore readabilityFlesch
    features
  }
}
"""

SIMILAR_ARTICLES_QUERY = """
query SimilarArticles($uniqueId: String!, $threshold: Float, $limit: Int) {
  similarArticles(uniqueId: $uniqueId, threshold: $threshold, limit: $limit) {
    uniqueId similarity
  }
}
"""

INTEGRITY_BATCH_QUERY = """
query IntegrityBatch($batchSize: Int) {
  integrityBatch(batchSize: $batchSize) {
    uniqueId url imageUrl publishedAt integrity
  }
}
"""

UPSERT_FEATURES_MUTATION = """
mutation UpsertFeatures($uniqueId: String!, $features: JSON!) {
  upsertFeatures(uniqueId: $uniqueId, features: $features)
}
"""

BATCH_UPSERT_FEATURES_MUTATION = """
mutation BatchUpsertFeatures($items: [FeatureUpsertInput!]!) {
  batchUpsertFeatures(items: $items) {
    processed failed
  }
}
"""

UPDATE_TYPESENSE_FIELD_MUTATION = """
mutation UpdateTypesenseField($uniqueId: String!, $field: String!, $value: JSON!) {
  updateTypesenseField(uniqueId: $uniqueId, field: $field, value: $value)
}
"""
