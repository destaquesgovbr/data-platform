"""Thumbnail Worker — FastAPI application.

Cloud Run service that receives Pub/Sub push messages from
dgb.news.enriched topic, generates thumbnails for video news
without images, and stores them in GCS.
"""

import base64
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from data_platform.config import get_settings
from data_platform.managers.postgres_manager import PostgresManager
from data_platform.workers.thumbnail_worker.handler import handle_thumbnail_generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize PostgresManager on startup, close on shutdown."""
    app.state.pg = PostgresManager()
    yield
    app.state.pg.close_all()


app = FastAPI(title="Thumbnail Worker", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/process")
async def process(request: Request):
    """Handle Pub/Sub push message from dgb.news.enriched."""
    try:
        envelope = await request.json()
    except Exception:
        return PlainTextResponse(status_code=400, content="Invalid JSON")

    message = envelope.get("message", {})
    data_b64 = message.get("data")
    if not data_b64:
        return PlainTextResponse(status_code=400, content="No data")

    try:
        payload = json.loads(base64.b64decode(data_b64))
    except Exception:
        return PlainTextResponse(status_code=400, content="Invalid data encoding")

    unique_id = payload.get("unique_id")
    if not unique_id:
        return PlainTextResponse(status_code=400, content="Missing unique_id")

    trace_id = message.get("attributes", {}).get("trace_id", "")
    logger.info(f"Processing {unique_id} (trace={trace_id})")

    settings = get_settings()
    bucket_name = settings.gcs_bucket

    try:
        pg = request.app.state.pg
        result = handle_thumbnail_generation(unique_id, pg, bucket_name)
        logger.info(f"Result for {unique_id}: {result['status']}")
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Unhandled error for {unique_id}: {e}", exc_info=True)
        return JSONResponse(status_code=200, content={"status": "error", "unique_id": unique_id})
