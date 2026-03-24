"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import router
from app.services import llm_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate LLM API env at startup (no local model download)."""
    logger.info("Starting application lifespan: validating LLM API configuration...")
    try:
        llm_service.load_model()
    except Exception:
        logger.exception("LLM API configuration failed at startup")
        raise
    yield
    logger.info("Application shutdown.")


app = FastAPI(
    title="Flight Ticket Extraction API",
    description=(
        "Extract structured fields from flight ticket PDFs using an "
        "OpenAI-compatible chat API (open-weights / open models by provider)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
