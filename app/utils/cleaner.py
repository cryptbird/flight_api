"""Text normalization and light de-noising for PDF/OCR output."""

from __future__ import annotations

import regex as re


def clean_ticket_text(raw: str) -> str:
    """
    Remove obvious OCR/PDF noise and normalize whitespace.

    Args:
        raw: Raw extracted text from pdfplumber or OCR.

    Returns:
        Cleaned single string suitable for prompting and regex.
    """
    if not raw:
        return ""
    # Replace common weird whitespace and zero-width chars
    text = raw.replace("\x00", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    # Collapse whitespace runs
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" *\n *", "\n", text)
    # Drop lines that are only punctuation/numbers noise (very short)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    kept: list[str] = []
    for ln in lines:
        if len(ln) <= 2 and re.fullmatch(r"[^\w]{1,2}", ln):
            continue
        kept.append(ln)
    text = "\n".join(kept)
    return text.strip()
