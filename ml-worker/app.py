"""ML worker — Hugging Face OCR engines over HTTP.

Loads model weights once at first request and caches them. The backend's
grading service calls these endpoints when OCR_ENGINE selects a Hugging Face
model.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import fitz  # PyMuPDF
import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ml-worker")

app = FastAPI(title="GradeOps ML worker", version="0.1.0")

_DEVICE = "cpu"


@lru_cache(maxsize=1)
def _nougat() -> tuple[Any, Any]:
    """Load (and cache) facebook/nougat-small."""
    from transformers import NougatProcessor, VisionEncoderDecoderModel

    log.info("loading facebook/nougat-small …")
    processor = NougatProcessor.from_pretrained("facebook/nougat-small")
    model = VisionEncoderDecoderModel.from_pretrained("facebook/nougat-small")
    model.to(_DEVICE)
    model.eval()
    log.info("nougat-small ready")
    return processor, model


def _pdf_to_images(pdf_bytes: bytes, dpi: int = 200) -> list[Image.Image]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    images: list[Image.Image] = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(img)
    finally:
        doc.close()
    return images


def _crude_confidence(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.0
    # No real confidence metric from nougat; approximate by useful text length.
    return min(1.0, len(t) / 200)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr/nougat")
async def ocr_nougat(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "missing filename")

    pdf_bytes = await file.read()
    try:
        images = _pdf_to_images(pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"could not rasterise PDF: {exc}") from exc
    if not images:
        raise HTTPException(400, "PDF had no pages")

    processor, model = _nougat()
    pages: list[str] = []
    for idx, img in enumerate(images):
        try:
            # Bypass NougatProcessor.__call__ here — it forwards do_crop_margin=None
            # to the image_processor, which trips strict kwarg validation. Calling
            # image_processor directly with no overrides uses its instance defaults.
            pixel_values = processor.image_processor(
                img, return_tensors="pt"
            ).pixel_values
            with torch.no_grad():
                outputs = model.generate(
                    pixel_values.to(_DEVICE),
                    min_length=1,
                    max_new_tokens=1024,
                    bad_words_ids=[[processor.tokenizer.unk_token_id]],
                )
            text = processor.batch_decode(outputs, skip_special_tokens=True)[0]
            text = processor.post_process_generation(text, fix_markdown=False)
        except Exception as exc:  # noqa: BLE001
            log.exception("nougat failed on page %d of %s", idx, file.filename)
            text = ""
            raise HTTPException(500, f"OCR failed on page {idx}: {exc}") from exc
        pages.append(text.strip())

    combined = "\n\n".join(p for p in pages if p)
    return {
        "filename": file.filename,
        "engine": "nougat",
        "pages": pages,
        "text": combined,
        "confidence": round(_crude_confidence(combined), 2),
    }
