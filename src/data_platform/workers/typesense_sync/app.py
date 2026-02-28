"""
Typesense Sync Worker — FastAPI application.

Cloud Run service that receives Pub/Sub push messages and upserts
articles to the Typesense search index.

Subscribes to:
  - dgb.news.enriched  (article classified with themes + summary)
  - dgb.news.embedded   (article embedding generated)
"""

import base64
import json

from fastapi import FastAPI, Request, Response
from loguru import logger

from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.typesense_sync.handler import upsert_to_typesense

app = FastAPI(title="Typesense Sync Worker", version="1.0.0")

# Lazy-initialized shared PostgresManager
_pg: PostgresManager | None = None


def _get_pg() -> PostgresManager:
    global _pg
    if _pg is None:
        _pg = PostgresManager(max_connections=5)
    return _pg


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/process")
async def process(request: Request) -> Response:
    """
    Handle Pub/Sub push message.

    Pub/Sub sends a JSON envelope:
    {
      "message": {
        "data": "<base64-encoded JSON>",
        "attributes": {...},
        "messageId": "..."
      },
      "subscription": "projects/.../subscriptions/..."
    }

    Returns 200 to ACK, 400/500 to NACK (triggers retry).
    """
    try:
        envelope = await request.json()
    except Exception:
        logger.error("Invalid JSON in request body")
        return Response(status_code=400, content="Invalid JSON")

    message = envelope.get("message", {})
    data_b64 = message.get("data")
    if not data_b64:
        logger.error("No data in Pub/Sub message")
        return Response(status_code=400, content="No data")

    try:
        payload = json.loads(base64.b64decode(data_b64))
    except Exception:
        logger.error("Failed to decode message data")
        return Response(status_code=400, content="Invalid data encoding")

    unique_id = payload.get("unique_id")
    if not unique_id:
        logger.error(f"Missing unique_id in message: {payload}")
        return Response(status_code=400, content="Missing unique_id")

    trace_id = message.get("attributes", {}).get("trace_id", "")
    logger.info(f"Processing {unique_id} (trace={trace_id})")

    success = upsert_to_typesense(unique_id, pg=_get_pg())

    if success:
        return Response(status_code=200, content="OK")

    # Return 200 even on failure to avoid infinite retries for poison messages.
    # The article will be picked up by the reconciliation DAG.
    logger.warning(f"Upsert failed for {unique_id}, ACKing to avoid retry loop")
    return Response(status_code=200, content="ACK (failed)")
