"""Scanned-PDF → text extraction via Gemini Vision.

Used by the backend grading service when OCR_ENGINE=gemini. Each PDF must be
named `{student_id}_{question_id}.pdf` (e.g. `STU001_Q1.pdf`) so we can map
the extracted text back to the rubric.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from pathlib import Path
from typing import Callable

import fitz  # type: ignore
from langchain_core.messages import HumanMessage

log = logging.getLogger(__name__)


OCR_PROMPT = """You are an OCR assistant working on a scanned exam page.

Extract the student's handwritten or typed answer VERBATIM as plain text.
- Preserve the student's exact wording, including spelling errors, math notation, and pseudocode.
- Do NOT correct, summarize, or add commentary.
- If a region is illegible, write [illegible] in place.
- If the page is blank, return an empty string.

Output ONLY the extracted text. No preamble, no headers, no markdown fences."""


_FILENAME_RE = re.compile(
    r"^(?P<student>[A-Za-z0-9]+)_(?P<question>[A-Za-z0-9]+)\.pdf$",
    re.IGNORECASE,
)


def parse_filename(name: str) -> tuple[str, str] | None:
    """Parse `STU001_Q1.pdf` → ("STU001", "Q1"). Returns None on mismatch."""
    match = _FILENAME_RE.match(Path(name).name)
    if not match:
        return None
    return (match.group("student").upper(), match.group("question").upper())


def pdf_to_page_pngs(pdf_bytes: bytes, dpi: int = 200, max_pages: int = 8) -> list[bytes]:
    """Render each PDF page to raw PNG bytes. Capped at `max_pages`."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: list[bytes] = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                log.warning("PDF has %d pages; truncating to %d", doc.page_count, max_pages)
                break
            pix = page.get_pixmap(dpi=dpi)
            pages.append(pix.tobytes("png"))
    finally:
        doc.close()
    return pages


def pdf_to_image_blocks(pdf_bytes: bytes, dpi: int = 200, max_pages: int = 8) -> list[dict]:
    """Render each PDF page to a base64 PNG wrapped as a LangChain image block."""
    blocks: list[dict] = []
    for png in pdf_to_page_pngs(pdf_bytes, dpi=dpi, max_pages=max_pages):
        b64 = base64.b64encode(png).decode()
        blocks.append(
            {
                "type": "image_url",
                "image_url": f"data:image/png;base64,{b64}",
            }
        )
    return blocks


async def extract_text_from_pdf(pdf_bytes: bytes, llm, dpi: int = 200) -> tuple[str, float]:
    """Send the PDF as image(s) to Gemini Vision.

    Returns (extracted_text, heuristic_confidence). Gemini doesn't return a
    self-confidence score, so we derive one from the text content.
    """
    image_blocks = pdf_to_image_blocks(pdf_bytes, dpi=dpi)
    if not image_blocks:
        return "", 0.0
    message = HumanMessage(
        content=[
            {"type": "text", "text": OCR_PROMPT},
            *image_blocks,
        ]
    )
    response = await llm.ainvoke([message])
    content = response.content if isinstance(response.content, str) else str(response.content)
    text = content.strip()
    return text, _confidence_from_text(text)


def _confidence_from_text(text: str) -> float:
    """Crude heuristic — Gemini doesn't return a self-confidence score.

    - empty / whitespace → 0.0 (will trip UNREADABLE in grading)
    - contains `[illegible]` markers → 0.55 (will trip LOW_OCR_CONFIDENCE)
    - else → 0.9 (treated as clean)
    """
    stripped = text.strip()
    if not stripped:
        return 0.0
    if "[illegible]" in stripped.lower():
        return 0.55
    return 0.9


async def extract_from_pdfs(
    files: list[tuple[str, bytes]],
    llm=None,
    engine: str = "gemini",
    dpi: int = 200,
    max_concurrency: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Extract text from a list of (filename, pdf_bytes) tuples.

    `engine` must be "gemini" — Gemini Vision via the LangChain `llm` instance.
    (The alternative nougat engine lives in the ml-worker service and is called
    through `app.services.ocr_client` instead of this module.)

    Returns per-file dicts:
        {"student_id", "question_id", "text", "ocr_confidence",
         "source_file", "engine", "pdf_bytes"}
        or {"filename", "error", "engine"} on failure.
    """
    sem = asyncio.Semaphore(max_concurrency)
    total = len(files)
    completed = 0
    lock = asyncio.Lock()

    if engine != "gemini":
        raise ValueError(f"Unknown OCR engine: {engine!r}")

    async def run_one(filename: str, content: bytes) -> dict:
        nonlocal completed
        parsed = parse_filename(filename)
        if parsed is None:
            result = {
                "filename": filename,
                "engine": engine,
                "error": (
                    f"Bad filename: expected '{{student_id}}_{{question_id}}.pdf' "
                    f"(e.g. STU001_Q1.pdf), got '{filename}'."
                ),
            }
        else:
            sid, qid = parsed
            async with sem:
                try:
                    if llm is None:
                        raise ValueError("Gemini engine requires a langchain `llm` instance.")
                    text, conf = await extract_text_from_pdf(content, llm, dpi=dpi)
                    result = {
                        "student_id": sid,
                        "question_id": qid,
                        "text": text,
                        "ocr_confidence": conf,
                        "source_file": filename,
                        "engine": engine,
                        "pdf_bytes": content,  # carried through so the storage layer can save the original
                    }
                except Exception as exc:  # noqa: BLE001
                    log.exception("PDF extraction failed for %s", filename)
                    result = {
                        "filename": filename,
                        "engine": engine,
                        "error": f"Extraction failed: {type(exc).__name__}: {exc}",
                    }
        async with lock:
            completed += 1
            if on_progress:
                try:
                    on_progress(completed, total)
                except Exception:  # noqa: BLE001
                    log.exception("on_progress callback raised")
        return result

    return await asyncio.gather(*[run_one(n, c) for n, c in files])


def group_by_student(extractions: list[dict]) -> list[dict]:
    """Fold successful extractions into the nested shape grade_exam expects."""
    grouped: dict[str, list[dict]] = {}
    for ext in extractions:
        if "error" in ext:
            continue
        grouped.setdefault(ext["student_id"], []).append(
            {
                "question_id": ext["question_id"],
                "text": ext["text"],
                "ocr_confidence": ext["ocr_confidence"],
            }
        )
    return [
        {"student_id": sid, "answers": answers}
        for sid, answers in sorted(grouped.items())
    ]
