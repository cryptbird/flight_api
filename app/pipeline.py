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


def _merge_passengers_fragments(ticket: FlightTicketData) -> FlightTicketData:
    """
    Heuristic: some tickets show a single passenger name split across lines
    (e.g. SURNAME/GIVENNAME+TITLE) and LLM may output multiple passenger objects.

    If multiple passengers share the same non-empty ticketNumber, we merge them
    back into one passenger (seatNumber keeps the first non-empty value).
    """

    passengers = ticket.passengers or []
    if len(passengers) <= 1:
        return ticket

    # If ticketNumber is present, it's the best stable grouping key.
    with_ticket = [p for p in passengers if (p.ticketNumber or "").strip()]
    if not with_ticket:
        # No reliable grouping key; don't guess.
        return ticket

    junk_tokens = {
        "AGT",
        "MR",
        "MRS",
        "MS",
        "MASTER",
        "DR",
    }

    def _strip_title_suffix(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        up = s.upper()
        for t in ["MR", "MRS", "MS", "MASTER", "DR"]:
            if up.endswith(t):
                s = s[: -len(t)].strip()
                break
        return s

    def _clean_name_part(s: str) -> str:
        s = _strip_title_suffix(s)
        up = (s or "").strip().upper()
        if up in junk_tokens:
            return ""
        return (s or "").strip()

    def _merge_group(group: list) -> dict:
        # Choose base fields from first passenger with ticketNumber.
        base = group[0]
        merged: dict = {
            "passengerId": 0,
            "firstName": "",
            "lastName": "",
            "type": base.type or "",
            "ticketNumber": base.ticketNumber or "",
            "seatNumber": "",
        }

        # Seat: keep the first non-empty seatNumber.
        for p in group:
            if (p.seatNumber or "").strip():
                merged["seatNumber"] = p.seatNumber.strip()
                break

        # Merge name fragments:
        cleaned = []
        for p in group:
            fn = _clean_name_part(p.firstName)
            ln = _clean_name_part(p.lastName)
            cleaned.append((fn, ln))

        # Heuristic:
        # - If one fragment has an empty/junk lastName, treat its firstName as surname.
        # - The remaining first/last parts are treated as the given name.
        surname_candidate = ""
        surname_idx = -1
        for i, (fn, ln) in enumerate(cleaned):
            if fn and not ln:
                surname_candidate = fn
                surname_idx = i
                break

        given_parts: list[str] = []
        for i, (fn, ln) in enumerate(cleaned):
            if surname_idx == i:
                continue
            if fn:
                given_parts.append(fn)
            if ln:
                given_parts.append(ln)

        if surname_candidate:
            merged["lastName"] = surname_candidate
            merged["firstName"] = " ".join(given_parts).strip()
        else:
            # Fallback: use longest combined name fragment.
            best = ""
            best_fn = ""
            best_ln = ""
            for fn, ln in cleaned:
                combined = (fn + " " + ln).strip()
                if len(combined) > len(best):
                    best = combined
                    best_fn = fn
                    best_ln = ln
            merged["firstName"] = best_fn
            merged["lastName"] = best_ln

        merged["type"] = base.type or merged["type"]
        merged["ticketNumber"] = base.ticketNumber or merged["ticketNumber"]
        return merged  # type: ignore[return-value]

    # Group by ticketNumber while preserving original order.
    by_ticket: dict[str, list] = {}
    ordered_keys: list[str] = []
    for p in passengers:
        key = (p.ticketNumber or "").strip()
        if not key:
            continue
        if key not in by_ticket:
            by_ticket[key] = []
            ordered_keys.append(key)
        by_ticket[key].append(p)

    merged_passengers = []
    passenger_id = 1
    for key in ordered_keys:
        group = by_ticket.get(key) or []
        if len(group) == 1:
            merged_passengers.append(group[0])
        else:
            # Only merge when the fragments look like they come from a single name
            # (common artifacts like `AGT`/titles leaking into the lastName field).
            fragmentation_evidence = any(
                (p.lastName or "").strip() and not _clean_name_part(p.lastName)
                for p in group
            )
            if fragmentation_evidence:
                merged_payload = _merge_group(group)
                merged_passengers.append(merged_payload)
            else:
                merged_passengers.extend(group)
        passenger_id += 1

    # Renumber passengerId sequentially after merging.
    renumbered = []
    for i, p in enumerate(merged_passengers, start=1):
        if isinstance(p, dict):
            p["passengerId"] = i
            renumbered.append(p)
        else:
            p.passengerId = i  # type: ignore[misc]
            renumbered.append(p)

    return FlightTicketData.model_validate({**ticket.model_dump(), "passengers": renumbered})


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
            ticket = _merge_regex_hints(ticket, hints)
            ticket = _merge_passengers_fragments(ticket)
            return ticket
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Attempt %s: validation failed: %s", attempt + 1, last_error)
            continue

    raise RuntimeError(
        f"LLM did not return valid JSON after {_MAX_LLM_ATTEMPTS} attempts: {last_error}"
    )
