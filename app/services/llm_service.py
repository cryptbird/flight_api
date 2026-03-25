"""OpenAI-compatible LLM HTTP client for structured flight ticket extraction."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

from app.services.regex_service import RegexHints

logger = logging.getLogger(__name__)

_API_BASE: Optional[str] = None
_API_KEY: Optional[str] = None
_MODEL: Optional[str] = None


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else default


def load_model() -> None:
    """
    Validate LLM API configuration at startup (no local model weights).

    Required environment variables:

    - ``LLM_API_BASE`` — OpenAI-compatible base URL (no trailing path segments
      after ``/v1``), e.g. ``https://api.groq.com/openai/v1``
    - ``LLM_API_KEY`` — Bearer token for the provider
    - ``LLM_MODEL`` — Model id as defined by that provider
    """
    global _API_BASE, _API_KEY, _MODEL

    base = _env("LLM_API_BASE").rstrip("/")
    key = _env("LLM_API_KEY")
    model = _env("LLM_MODEL")

    if not base or not key or not model:
        raise RuntimeError(
            "LLM API not configured. Set LLM_API_BASE, LLM_API_KEY, and LLM_MODEL "
            "(OpenAI-compatible chat completions). See README for examples."
        )

    _API_BASE = base
    _API_KEY = key
    _MODEL = model
    logger.info("LLM API configured (model=%s, base=%s)", model, base)


def is_model_loaded() -> bool:
    """Return True if startup validation stored API settings."""
    return _API_BASE is not None and _API_KEY is not None and _MODEL is not None


def _chat_completions_url() -> str:
    if _API_BASE is None:
        raise RuntimeError("LLM not configured; load_model() must run at startup")
    return f"{_API_BASE}/chat/completions"


def _ensure_llm_config() -> None:
    """Load config on demand (Vercel ASGI often does not run FastAPI lifespan)."""
    if not is_model_loaded():
        load_model()


def _call_chat_api(user_prompt: str) -> str:
    """POST /chat/completions and return assistant message content."""
    _ensure_llm_config()
    if _API_KEY is None or _MODEL is None:
        raise RuntimeError("LLM not configured; set LLM_API_BASE, LLM_API_KEY, LLM_MODEL")

    max_tokens = int(_env("LLM_MAX_TOKENS", "500"))
    temperature = float(_env("LLM_TEMPERATURE", "0.1"))
    timeout = float(_env("LLM_TIMEOUT_SECONDS", "120"))

    payload: Dict[str, Any] = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }

    url = _chat_completions_url()

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise RuntimeError(f"LLM API request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text[:2000] if response.text else "(empty body)"
        raise RuntimeError(
            f"LLM API error HTTP {response.status_code}: {detail}"
        )

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM API response shape: {data!r}") from exc

    if not content or not str(content).strip():
        raise RuntimeError("LLM API returned empty content")

    return str(content).strip()


def build_extraction_prompt(clean_text: str, hints: RegexHints) -> str:
    """
    Build the primary extraction prompt with definitions and a concrete example.

    Args:
        clean_text: Normalized ticket text.
        hints: Regex-derived PNR and flight number hints (may be empty).
    """
    hint_line = ""
    if hints.pnr or hints.flight_number:
        hint_line = (
            "Regex hints (use if they clearly match the ticket, else infer from text): "
            f"pnr={hints.pnr or 'unknown'}, flight_number={hints.flight_number or 'unknown'}.\n"
        )

    example_in = (
        "PASSENGER 1: Khushvardhan Bhardwaj (ADT)  TICKET:  /  SEAT: 19F\n"
        "PASSENGER 2: Khush Bhardwaj (ADT) TICKET:  /  SEAT: 19E\n"
        "PNR: V9HQ4V\n"
        "FLIGHT: SG651 JAI (Terminal 2) 11JAN2026 18:15 -> BOM (Terminal 1) 11JAN2026 20:10\n"
        "AIRLINE: SpiceJet  CLASS: Economy"
    )
    example_out = (
        '{'
        '"pnr":"V9HQ4V",'
        '"bookingDate":"2026-11-12T00:00:00",'
        '"passengers":['
        '{"passengerId":1,"firstName":"Khushvardhan","lastName":"Bhardwaj","type":"ADT","ticketNumber":"","seatNumber":"19F"},'
        '{"passengerId":2,"firstName":"Khush","lastName":"Bhardwaj","type":"ADT","ticketNumber":"","seatNumber":"19E"}'
        '],'
        '"flightDetails":['
        '{'
        '"segmentId":1,'
        '"airlineName":"SpiceJet",'
        '"airlineCode":"SG",'
        '"flightNumber":"SG651",'
        '"departure":{"airportCode":"JAI","city":"Jaipur","terminal":"2","dateTime":"2026-01-11T18:15:00"},'
        '"arrival":{"airportCode":"BOM","city":"Mumbai","terminal":"1","dateTime":"2026-01-11T20:10:00"},'
        '"travelClass":"Economy",'
        '"bookingClass":"",'
        '"status":""'
        '}'
        ']'
        '}'
    )

    return f"""You extract structured flight ticket data for downstream APIs.

Task: read the ticket text and return ONLY a single valid JSON object (no markdown, no code fences, no commentary).

JSON rules (schema is strict):
Return ONLY raw JSON beginning with {{ and ending with }}.

Top-level keys (exactly these):
- pnr (string)
- bookingDate (string ISO-8601 like 2026-11-12T00:00:00; use "" if unknown)
- passengers (array)
- flightDetails (array)

Passenger item schema (exact keys, no extras):
- passengerId (integer, 1-based; must be unique within passengers[])
- firstName (string; use "" if unknown)
- lastName (string; use "" if unknown)
- type (string like "ADT"/"CHD"/"INF" if present, else "")
- ticketNumber (string; use "" if unknown)
- seatNumber (string; use "" if unknown)

Flight segment schema (exact keys, no extras):
- segmentId (integer, 1-based within flightDetails[])
- airlineName (string; use "" if unknown)
- airlineCode (string; use "" if unknown)
- flightNumber (string; use "" if unknown)
- departure (object with exact keys airportCode, city, terminal, dateTime)
- arrival (object with exact keys airportCode, city, terminal, dateTime)
- travelClass (string; use "" if unknown)
- bookingClass (string; use "" if unknown)
- status (string; use "" if unknown)

departure/arrival object schema:
- airportCode (string; use "" if unknown)
- city (string; use "" if unknown)
- terminal (string; use "" if unknown)
- dateTime (string ISO-8601 like 2026-01-11T18:15:00; use "" if unknown)

Important:
- If the ticket has multiple passengers, return all of them in passengers[] (do not collapse into one).
- For each passenger, pick the seat number associated with that passenger if available.
- Output one passenger object per person in the ticket. Do not create extra passengers just because seat number differs across flight segments (it is segment-specific).
- If the ticket shows a single passenger, parse the full name (including formats like `SURNAME/GIVENNAME+TITLE`) into first/last, and still return exactly one passenger.
- If you cannot confidently determine first vs last name, keep the best split; never omit fields.

Example ticket text:
{example_in}

Example output (valid JSON only):
{example_out}

{hint_line}Ticket text to parse:
{clean_text}

Output (JSON only):"""


def build_correction_prompt(previous_output: str, validation_error: str) -> str:
    """
    Ask the model to fix invalid JSON or schema mismatches.

    Args:
        previous_output: Raw model output from the prior attempt.
        validation_error: Human-readable validation failure reason.
    """
    return f"""Fix this JSON to match the schema exactly.

Schema (strict):
Top-level JSON object with ONLY these keys:
pnr, bookingDate, passengers, flightDetails

passengers: array of objects with ONLY these keys:
passengerId, firstName, lastName, type, ticketNumber, seatNumber

flightDetails: array of objects with ONLY these keys:
segmentId, airlineName, airlineCode, flightNumber, departure, arrival, travelClass, bookingClass, status

departure/arrival objects with ONLY these keys:
airportCode, city, terminal, dateTime

Rules:
- Use "" for unknown string fields.
- passengerId and segmentId must be integers.
- Do not wrap in markdown or add commentary.

Validation error:
{validation_error}

Broken model output:
{previous_output}

Return ONLY valid JSON. No explanations."""


def run_extraction_prompt(user_prompt: str) -> str:
    """Call the remote LLM with the full user prompt and return assistant text."""
    return _call_chat_api(user_prompt)
