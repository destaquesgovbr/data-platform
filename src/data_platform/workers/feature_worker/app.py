"""Feature Worker — FastAPI application.

Cloud Run service that receives Pub/Sub push messages from
dgb.news.enriched topic, computes local features, and stores
them in news_features table.
"""

import base64
import json
import logging
import os

from fastapi import FastAPI, Request, Response

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.feature_worker.handler import handle_feature_computation

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Feature Worker", version="1.0.0")

_pg: PostgresManager | None = None
_gql_client = None


def _get_pg() -> PostgresManager:
    global _pg
    if _pg is None:
        _pg = PostgresManager()
    return _pg


def _get_gql_client():
    global _gql_client
    if _gql_client is None:
        graphql_url = os.environ.get("GRAPHQL_API_URL")
        if graphql_url:
            from data_platform.clients.graphql_client import GraphQLClient

            _gql_client = GraphQLClient(url=graphql_url)
    return _gql_client


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/process")
async def process(request: Request) -> Response:
    """Handle Pub/Sub push message from dgb.news.enriched."""
    try:
        envelope = await request.json()
    except Exception:
        return Response(status_code=400, content="Invalid JSON")

    message = envelope.get("message", {})
    data_b64 = message.get("data")
    if not data_b64:
        return Response(status_code=400, content="No data")

    try:
        payload = json.loads(base64.b64decode(data_b64))
    except Exception:
        return Response(status_code=400, content="Invalid data encoding")

    unique_id = payload.get("unique_id")
    if not unique_id:
        return Response(status_code=400, content="Missing unique_id")

    trace_id = message.get("attributes", {}).get("trace_id", "")
    logger.info(f"Processing {unique_id} (trace={trace_id})")

    try:
        result = handle_feature_computation(unique_id, _get_pg(), gql_client=_get_gql_client())
        logger.info(f"Result for {unique_id}: {result['status']}")
        return Response(status_code=200, content=json.dumps(result))
    except Exception as e:
        logger.error(f"Unhandled error for {unique_id}: {e}", exc_info=True)
        return Response(status_code=200, content=f"ACK (error: {e})")
