"""End-to-end orchestration: PDF → text → clean → regex hints → LLM → validated JSON."""

from __future__ import annotations

import logging
from typing import Final

from app.models.schema import FlightTicketData
from app.services import llm_service
from app.services.ocr_service import ocr_pdf_bytes
from app.services.parser_service import extract_json_object, parse_flight_ticket_json
from app.services.pdf_service import extract_text_pdfplumber, is_text_layer_too_weak
from app.services.regex_service import RegexHints, extract_regex_hints
from app.utils.cleaner import clean_ticket_text

logger = logging.getLogger(__name__)

_MAX_LLM_ATTEMPTS: Final[int] = 3
_PDF_MAGIC_PREFIX: Final[bytes] = b"%PDF"
_MIN_TEXT_CHARS: Final[int] = 50


def _merge_regex_hints(ticket: FlightTicketData, hints: RegexHints) -> FlightTicketData:
    """
    Complement LLM output with regex hints when corresponding fields are empty.
    """
    data = ticket.model_dump()
    if not data.get("pnr", "").strip() and hints.pnr:
        data["pnr"] = hints.pnr

    # Fill flight number into the first segment that doesn't have it yet.
    if hints.flight_number:
        segments = data.get("flightDetails") or []
        for seg in segments:
            if not (seg.get("flightNumber") or "").strip():
                seg["flightNumber"] = hints.flight_number
                break

    return FlightTicketData.model_validate(data)


def _validate_pdf_magic(file_bytes: bytes) -> None:
    if not file_bytes:
        raise ValueError("Empty file upload")
    if not file_bytes.startswith(_PDF_MAGIC_PREFIX):
        raise ValueError("Invalid file type: not a PDF")


def extract_ticket_from_pdf(file_bytes: bytes) -> FlightTicketData:
    """
    Run the mandatory pipeline on PDF bytes and return validated ticket data.

    Args:
        file_bytes: Raw PDF content.

    Returns:
        Validated FlightTicketData.

    Raises:
        ValueError: For invalid PDF, empty content, or unrecoverable extraction.
        RuntimeError: If LLM repeatedly fails to produce valid structured output.
    """
    _validate_pdf_magic(file_bytes)

    try:
        raw_text = extract_text_pdfplumber(file_bytes)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"PDF text extraction failed: {exc}") from exc

    used_ocr = False
    if is_text_layer_too_weak(raw_text, min_chars=_MIN_TEXT_CHARS):
        logger.info("Text layer weak or empty; running OCR fallback.")
        try:
            raw_text = ocr_pdf_bytes(file_bytes)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"OCR failure: {exc}") from exc
        used_ocr = True

    if not raw_text.strip():
        raise ValueError("Empty PDF: no text could be extracted")

    cleaned = clean_ticket_text(raw_text)
    if not cleaned:
        msg = "Empty PDF after cleaning"
        if used_ocr:
            msg += " (OCR produced no usable text — check Tesseract/Poppler or image quality)"
        raise ValueError(msg)

    hints = extract_regex_hints(cleaned)

    last_raw: str = ""
    last_error: str = ""

    for attempt in range(_MAX_LLM_ATTEMPTS):
        if attempt == 0:
            prompt = llm_service.build_extraction_prompt(cleaned, hints)
        else:
            prompt = llm_service.build_correction_prompt(last_raw, last_error)

        try:
            raw_out = llm_service.run_extraction_prompt(prompt)
        except Exception as exc:
            raise RuntimeError(f"LLM inference failed: {exc}") from exc

        last_raw = raw_out
        json_str = extract_json_object(raw_out)
        if not json_str:
            last_error = "Model output did not contain a parseable JSON object"
            logger.warning("Attempt %s: %s", attempt + 1, last_error)
            continue

        try:
            ticket = parse_flight_ticket_json(json_str)
            return _merge_regex_hints(ticket, hints)
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Attempt %s: validation failed: %s", attempt + 1, last_error)
            continue

    raise RuntimeError(
        f"LLM did not return valid JSON after {_MAX_LLM_ATTEMPTS} attempts: {last_error}"
    )
