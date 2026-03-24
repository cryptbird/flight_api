"""Extract and parse JSON objects from raw LLM output using regex and validation."""

from __future__ import annotations

import json
from typing import Optional

import regex as re

from app.models.schema import FlightTicketData

_FENCE_OPEN = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def _first_balanced_json_object(text: str) -> Optional[str]:
    """Return the first substring that is a balanced {...} and valid JSON."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def extract_json_object(raw_llm_output: str) -> Optional[str]:
    """
    Pull a single JSON object string from model output.

    Prefers fenced ```json blocks; falls back to first balanced {...} that parses.

    Args:
        raw_llm_output: Unparsed model completion.

    Returns:
        JSON object as string, or None if not found.
    """
    if not raw_llm_output:
        return None

    text = raw_llm_output.strip()

    for m in _FENCE_OPEN.finditer(text):
        inner_start = m.end()
        rest = text[inner_start:]
        close_idx = rest.find("```")
        if close_idx == -1:
            continue
        inner = rest[:close_idx]
        found = _first_balanced_json_object(inner)
        if found:
            return found

    return _first_balanced_json_object(text)


def parse_flight_ticket_json(json_str: str) -> FlightTicketData:
    """
    Parse JSON string into FlightTicketData with Pydantic validation.

    Args:
        json_str: JSON object string.

    Returns:
        Validated model.

    Raises:
        ValueError: On invalid JSON or schema mismatch.
    """
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    try:
        return FlightTicketData.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"Schema validation failed: {exc}") from exc
