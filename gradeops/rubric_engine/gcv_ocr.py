"""Google Cloud Vision adapter for handwriting OCR.

Uses the `DOCUMENT_TEXT_DETECTION` feature, which is tuned for dense /
handwritten text — meaningfully better than `TEXT_DETECTION` for messy
exam scans.

Setup:
    1. Enable the Cloud Vision API in your GCP project (one-click in console).
    2. Authenticate one of these ways:
         - gcloud auth application-default login            (easiest, dev only)
         - GOOGLE_APPLICATION_CREDENTIALS=/abs/path/to/sa.json
    3. Pick "Google Cloud Vision" in the OCR-engine selector in the Streamlit
       sidebar.

Pricing: first 1000 pages/month free, then $1.50 per 1000 pages — very
generous for a typical exam-grading batch.

Each page of the PDF is rasterized to PNG (via the shared `pdf_to_page_pngs`)
and sent as one Vision API request. Word-level confidences are averaged into
the `ocr_confidence` value the grading pipeline consumes downstream.
"""
from __future__ import annotations

import asyncio
import logging
from statistics import mean

from google.cloud import vision  # type: ignore

from .pdf_ocr import pdf_to_page_pngs

log = logging.getLogger(__name__)


_client: vision.ImageAnnotatorClient | None = None


def _get_client() -> vision.ImageAnnotatorClient:
    """Lazily build a singleton Vision client. Picks up ADC or
    GOOGLE_APPLICATION_CREDENTIALS automatically."""
    global _client
    if _client is None:
        _client = vision.ImageAnnotatorClient()
    return _client


def _extract_page_sync(png_bytes: bytes, language_hint: str = "en") -> tuple[str, float]:
    """Synchronous Vision call for a single PNG page.

    Returns (extracted_text, mean_word_confidence).
    """
    client = _get_client()
    image = vision.Image(content=png_bytes)
    image_context = vision.ImageContext(language_hints=[language_hint])
    response = client.document_text_detection(image=image, image_context=image_context)

    if response.error.message:
        raise RuntimeError(f"GCV error: {response.error.message}")

    full_text = response.full_text_annotation
    text = (full_text.text or "").strip()
    if not text:
        return "", 0.0

    # Average word-level confidence across the page. Block / page confidences
    # are often coarser than the word level.
    confidences: list[float] = []
    for page in full_text.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    confidences.append(float(word.confidence))
    confidence = mean(confidences) if confidences else 0.0
    return text, confidence


async def extract_text_from_pdf(pdf_bytes: bytes, dpi: int = 200) -> tuple[str, float]:
    """Run GCV OCR on each page of the PDF.

    Returns (joined_text, mean_confidence). Empty/blank pages contribute
    nothing to the confidence mean.
    """
    pages = pdf_to_page_pngs(pdf_bytes, dpi=dpi)
    if not pages:
        return "", 0.0

    texts: list[str] = []
    confidences: list[float] = []
    for i, png in enumerate(pages):
        # GCV's client is blocking; offload so the asyncio.gather() in the
        # caller can still run other PDFs concurrently.
        text, conf = await asyncio.to_thread(_extract_page_sync, png)
        if text:
            texts.append(text)
            confidences.append(conf)
        log.debug("GCV page %d: %d chars, conf=%.2f", i + 1, len(text), conf)

    combined = "\n\n".join(texts)
    if not combined.strip():
        return "", 0.0
    return combined, round(mean(confidences), 3)
