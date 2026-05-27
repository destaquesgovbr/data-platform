"""
GraphQL client for internal API calls from workers and DAGs.

Uses httpx for HTTP + google-auth for Cloud Run OIDC authentication.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_API_URL = os.environ.get("GRAPHQL_API_URL", "http://localhost:8000/graphql")


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

    def __init__(self, url: str | None = None, timeout: float = 30.0):
        self.url = url or GRAPHQL_API_URL
        self.timeout = timeout
        self._http_client = httpx.Client(timeout=timeout)

    def _get_auth_headers(self) -> dict[str, str]:
        """Get OIDC token for Cloud Run service-to-service auth."""
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            auth_request = google.auth.transport.requests.Request()
            token = google.oauth2.id_token.fetch_id_token(auth_request, self.url)
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

NEWS_BY_ID_QUERY = """
query NewsById($uniqueId: ID!) {
  newsById(uniqueId: $uniqueId) {
    uniqueId title url imageUrl videoUrl content summary subtitle
    editorialLead category tags agencyKey agencyName
    publishedAt extractedAt
    themL1Code themL1Label themL2Code themL2Label
    themL3Code themL3Label mostSpecificThemeCode mostSpecificThemeLabel
    features
  }
}
"""

NEWS_FOR_TYPESENSE_QUERY = """
query NewsForTypesense($uniqueId: ID!) {
  newsForTypesense(uniqueId: $uniqueId) {
    uniqueId title url imageUrl videoUrl content summary subtitle
    editorialLead category tags agencyKey agencyName
    publishedAt extractedAt
    themL1Code themL1Label themL2Code themL2Label
    themL3Code themL3Label mostSpecificThemeCode mostSpecificThemeLabel
    contentEmbedding sentimentLabel sentimentScore
    trendingScore wordCount hasImage hasVideo imageBroken readabilityFlesch
  }
}
"""

NEWS_BATCH_FOR_BIGQUERY_QUERY = """
query NewsBatchForBigQuery($startDate: DateTime!, $endDate: DateTime!, $batchSize: Int, $cursor: String) {
  newsBatchForBigQuery(startDate: $startDate, endDate: $endDate, batchSize: $batchSize, cursor: $cursor) {
    uniqueId title url agencyKey agencyName publishedAt
    themL1Code themL1Label themL2Code themL2Label
    themL3Code themL3Label mostSpecificThemeCode mostSpecificThemeLabel
    wordCount charCount paragraphCount hasImage hasVideo
    sentimentLabel sentimentScore readabilityFlesch publicationHour publicationDow
  }
}
"""

SIMILAR_ARTICLES_QUERY = """
query SimilarArticles($uniqueId: ID!, $threshold: Float, $limit: Int) {
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
mutation UpsertFeatures($uniqueId: ID!, $features: JSON!) {
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
mutation UpdateTypesenseField($uniqueId: ID!, $field: String!, $value: JSON!) {
  updateTypesenseField(uniqueId: $uniqueId, field: $field, value: $value)
}
"""
