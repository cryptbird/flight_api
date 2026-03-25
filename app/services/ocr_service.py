"""OCR fallback for PDFs/images.

Primary PDF rendering uses `pdf2image` (Poppler).
If Poppler isn't available, we fallback to PyMuPDF for page rasterization.
"""

from __future__ import annotations

import io
from typing import Iterable, List

from pdf2image import convert_from_bytes
from PIL import Image


def _pil_to_preprocessed_bgr(image: Image.Image):
    """Convert PIL image to OpenCV BGR after grayscale Otsu threshold."""
    import cv2
    import numpy as np

    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


def _ocr_pil_images(images: Iterable[Image.Image]) -> str:
    """Run OpenCV preprocessing + pytesseract OCR over PIL images."""
    import cv2
    import pytesseract

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


def ocr_image_bytes(image_bytes: bytes) -> str:
    """OCR for a single image (png/jpg/webp/etc) uploaded by the user."""
    if not image_bytes:
        raise RuntimeError("Empty image bytes for OCR")

    try:
        img = Image.open(io.BytesIO(image_bytes))  # type: ignore[name-defined]
    except Exception as exc:
        raise RuntimeError(f"Failed to read image: {exc}") from exc

    # Normalize to RGB for consistent preprocessing.
    img = img.convert("RGB")
    return _ocr_pil_images([img])


def ocr_pdf_bytes(pdf_bytes: bytes, dpi: int = 200) -> str:
    """
    Rasterize PDF pages and OCR each page with Tesseract after preprocessing.

    Heavy imports (cv2, pytesseract) are lazy so cold starts fail less often on
    serverless when OCR is not needed.

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
    except Exception as exc_poppler:
        # Poppler often isn't available in serverless; fallback to PyMuPDF rendering.
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            rendered: list[Image.Image] = []
            for page in doc:
                pix = page.get_pixmap(dpi=dpi)
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                # Convert to RGB (strip alpha) for stable preprocessing.
                rendered.append(img.convert("RGB"))
            images = rendered
        except Exception as exc_fitz:
            raise RuntimeError(
                "pdf2image conversion failed (Poppler missing?) and PyMuPDF fallback failed. "
                f"pdf2image error: {exc_poppler}; PyMuPDF error: {exc_fitz}"
            ) from exc_fitz

    if not images:
        raise RuntimeError("No pages rendered from PDF for OCR")

    return _ocr_pil_images(images)
