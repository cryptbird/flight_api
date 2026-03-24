"""Heuristic regex extraction for PNR and flight number hints."""

from __future__ import annotations

from dataclasses import dataclass

import regex as re

__all__ = ["RegexHints", "extract_regex_hints"]


@dataclass(frozen=True)
class RegexHints:
    """Optional hints merged into LLM prompts."""

    pnr: str
    flight_number: str


# PNR: 5–7 alphanumeric booking codes (conservative 6-char default)
_PNR_PATTERN = re.compile(
    r"\b(?<!/)([A-Z0-9]{6})(?![A-Z0-9])\b",
    re.IGNORECASE,
)

# Prefer typical IATA-style flight numbers; IndiGo-style 6E#### handled explicitly
_FLIGHT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b([A-Z]{2}\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\b(6E\d{2,4})\b", re.IGNORECASE),
    re.compile(r"\b([A-Z]\d{3,4})\b", re.IGNORECASE),
)


def extract_regex_hints(text: str) -> RegexHints:
    """
    Extract best-effort PNR and flight number substrings from raw text.

    Flight candidates equal to the detected PNR are skipped to avoid
    three-letter+numeric PNRs being misread as flight numbers.

    Args:
        text: Cleaned ticket text.

    Returns:
        RegexHints with possibly empty strings when nothing matches.
    """
    if not text:
        return RegexHints(pnr="", flight_number="")

    pnr = ""
    for m in _PNR_PATTERN.finditer(text):
        candidate = m.group(1).upper()
        if candidate.isdigit() and len(candidate) < 6:
            continue
        pnr = candidate
        break

    pnr_upper = pnr.upper()
    flight = ""
    for pattern in _FLIGHT_PATTERNS:
        for m in pattern.finditer(text):
            cand = re.sub(r"\s+", "", m.group(1).upper())
            if pnr_upper and cand == pnr_upper:
                continue
            flight = cand
            break
        if flight:
            break

    return RegexHints(pnr=pnr, flight_number=flight)

