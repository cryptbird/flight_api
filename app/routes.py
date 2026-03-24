"""HTTP routes for ticket extraction API."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import JSONResponse

from app.pipeline import extract_ticket_from_pdf

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])


def _error_body(message: str) -> Dict[str, str]:
    return {"status": "error", "message": message}


@router.post("/extract", response_model=None)
async def extract_flight_data(file: UploadFile = File(...)) -> JSONResponse | Dict[str, Any]:
    """
    Accept a PDF flight ticket and return structured JSON via the extraction pipeline.

    Returns:
        Success envelope with ``data`` or error envelope with ``message``.
    """
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body("Invalid file type; PDF required"),
        )

    try:
        payload = await file.read()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Upload read failed")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body(f"Failed to read upload: {exc}"),
        )

    try:
        ticket = extract_ticket_from_pdf(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body(str(exc)),
        )
    except RuntimeError as exc:
        logger.exception("Pipeline runtime error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(str(exc)),
        )
    except Exception as exc:
        logger.exception("Unexpected extraction error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(f"Unexpected server error: {exc}"),
        )

    return {
        "status": "success",
        "data": ticket.model_dump(),
    }
