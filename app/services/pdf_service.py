"""PDF text extraction using pdfplumber."""

from __future__ import annotations

import io

import pdfplumber


def extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """
    Extract plain text from a PDF using pdfplumber.

    Args:
        pdf_bytes: Raw PDF file bytes.

    Returns:
        Concatenated page text, possibly empty if no extractable text layer.

    Raises:
        ValueError: If bytes are not a readable PDF.
    """
    if not pdf_bytes:
        raise ValueError("Empty PDF payload")

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            parts: list[str] = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                parts.append(text)
    except Exception as exc:  # pdfplumber wraps multiple backends
        raise ValueError(f"Failed to open or parse PDF: {exc}") from exc

    return "\n".join(parts).strip()


def is_text_layer_too_weak(text: str, min_chars: int = 50) -> bool:
    """
    Decide if extracted text is too short to trust without OCR.

    Args:
        text: Extracted text.
        min_chars: Minimum printable character threshold.

    Returns:
        True if OCR fallback should be considered.
    """
    compact = "".join(text.split())
    return len(compact) < min_chars
