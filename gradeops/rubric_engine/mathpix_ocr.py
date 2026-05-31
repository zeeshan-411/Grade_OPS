"""Mathpix v3/text adapter for messy handwriting + math OCR.

Mathpix is purpose-built for STEM handwriting (returns LaTeX for math). Each
page of the PDF is rasterized to PNG and sent to `/v3/text` as a data URI.

Setup:
    1. Sign up at https://accounts.mathpix.com/
    2. Add to .env:
           MATHPIX_APP_ID = 'your_app_id'
           MATHPIX_APP_KEY = 'your_app_key'
    3. Pick "Mathpix" in the OCR-engine selector in the Streamlit sidebar.

Free tier is currently 1000 requests/month (one page = one request). Errors
from Mathpix (missing creds, quota, network) propagate up as exceptions so
the calling layer can render them as per-file `error` rows.
"""
from __future__ import annotations

import base64
import logging
import os

import httpx

from .pdf_ocr import pdf_to_page_pngs

log = logging.getLogger(__name__)

MATHPIX_TEXT_URL = "https://api.mathpix.com/v3/text"
DEFAULT_TIMEOUT = 60.0


def _get_credentials() -> tuple[str, str]:
    app_id = os.environ.get("MATHPIX_APP_ID")
    app_key = os.environ.get("MATHPIX_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError(
            "Mathpix credentials missing. Set MATHPIX_APP_ID and MATHPIX_APP_KEY in .env."
        )
    return app_id, app_key


async def _ocr_single_page(png_bytes: bytes, client: httpx.AsyncClient) -> tuple[str, float]:
    """POST one PNG to /v3/text; return (text, confidence)."""
    app_id, app_key = _get_credentials()
    data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
    payload = {
        "src": data_uri,
        "formats": ["text"],
        # Wrap inline + block math with markdown-ish delimiters so the grading
        # prompt sees recognizable expressions instead of raw LaTeX commands.
        "math_inline_delimiters": ["$", "$"],
        "math_display_delimiters": ["$$", "$$"],
        # Modest cleanup — drop obvious header/footer noise, leave the answer text.
        "rm_spaces": True,
    }
    headers = {
        "app_id": app_id,
        "app_key": app_key,
        "Content-Type": "application/json",
    }
    response = await client.post(
        MATHPIX_TEXT_URL,
        json=payload,
        headers=headers,
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body and body["error"]:
        raise RuntimeError(f"Mathpix returned error: {body['error']}")
    text = body.get("text", "").strip()
    # Mathpix returns `confidence` for the whole image (0..1, sometimes absent).
    confidence = float(body.get("confidence", 0.0)) if text else 0.0
    return text, confidence


async def extract_text_from_pdf(pdf_bytes: bytes, dpi: int = 200) -> tuple[str, float]:
    """Run Mathpix OCR on each page, return (joined_text, mean_confidence)."""
    pages = pdf_to_page_pngs(pdf_bytes, dpi=dpi)
    if not pages:
        return "", 0.0

    texts: list[str] = []
    confidences: list[float] = []
    async with httpx.AsyncClient() as client:
        for i, png in enumerate(pages):
            text, conf = await _ocr_single_page(png, client)
            texts.append(text)
            confidences.append(conf)
            log.debug("Mathpix page %d: %d chars, conf=%.2f", i + 1, len(text), conf)

    combined = "\n\n".join(t for t in texts if t)
    # Trust Mathpix's reported confidence — it's a real number, not a heuristic.
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    if not combined.strip():
        # Blank/illegible page — let the grading pipeline flag UNREADABLE.
        return "", 0.0
    return combined, round(mean_conf, 3)
