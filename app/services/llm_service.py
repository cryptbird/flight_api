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
            f"Regex hints (use if they clearly match the ticket, else infer from text): "
            f"pnr={hints.pnr or 'unknown'}, flight_number={hints.flight_number or 'unknown'}.\n"
        )

    example_in = (
        "PASSENGER: DOE/JANE MRS\n"
        "PNR: X1Y2Z3  FLT AI101 DEL-BOM  12FEB2025 0915-1135\n"
        "AIR INDIA  GATE 12A  SEAT 14C  FARE INR 8450"
    )
    example_out = (
        '{"passenger_name":"Jane Doe","pnr":"X1Y2Z3","airline":"Air India",'
        '"flight_number":"AI101","departure_airport":"DEL","arrival_airport":"BOM",'
        '"departure_time":"0915","arrival_time":"1135","date":"2025-02-12",'
        '"seat":"14C","gate":"12A","price":"INR 8450"}'
    )

    return f"""You extract structured flight ticket data for downstream APIs.

Task: read the ticket text and return ONLY a single valid JSON object. No markdown, no code fences, no commentary.

JSON rules:
- Return ONLY raw JSON beginning with {{ and ending with }}.
- Every value must be a string (use "" when unknown).
- Required keys exactly (all strings):
  passenger_name, pnr, airline, flight_number, departure_airport, arrival_airport,
  departure_time, arrival_time, date, seat, gate, price

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

Schema: an object with ONLY these string keys (all values strings, use "" if missing):
passenger_name, pnr, airline, flight_number, departure_airport, arrival_airport,
departure_time, arrival_time, date, seat, gate, price

Validation error:
{validation_error}

Broken model output (extract and repair into one valid JSON object):
{previous_output}

Return ONLY valid JSON. No explanations."""


def run_extraction_prompt(user_prompt: str) -> str:
    """Call the remote LLM with the full user prompt and return assistant text."""
    return _call_chat_api(user_prompt)
