"""OCR fallback: pdf2image, OpenCV preprocessing, pytesseract."""

from __future__ import annotations

from typing import List

import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image


def _pil_to_preprocessed_bgr(image: Image.Image) -> np.ndarray:
    """Convert PIL image to OpenCV BGR after grayscale Otsu threshold."""
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Tesseract often works well on single channel passed as RGB triple
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


def ocr_pdf_bytes(pdf_bytes: bytes, dpi: int = 200) -> str:
    """
    Rasterize PDF pages and OCR each page with Tesseract after preprocessing.

    Args:
        pdf_bytes: Raw PDF bytes.
        dpi: Render resolution for pdf2image.

    Returns:
        Concatenated OCR text for all pages.

    Raises:
        RuntimeError: If conversion or OCR fails.
    """
    if not pdf_bytes:
        raise RuntimeError("Empty PDF bytes for OCR")

    try:
        images: List[Image.Image] = convert_from_bytes(pdf_bytes, dpi=dpi)
    except Exception as exc:
        raise RuntimeError(f"pdf2image conversion failed (is Poppler installed?): {exc}") from exc

    if not images:
        raise RuntimeError("No pages rendered from PDF for OCR")

    texts: list[str] = []
    for img in images:
        try:
            bgr = _pil_to_preprocessed_bgr(img)
            pil_for_tesseract = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            page_text = pytesseract.image_to_string(pil_for_tesseract) or ""
            texts.append(page_text)
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError(
                "Tesseract executable not found. Install Tesseract and ensure it is on PATH."
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"OCR failed: {exc}") from exc

    return "\n".join(texts).strip()
