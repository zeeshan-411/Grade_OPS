"""HTTP client for the ml-worker container (Hugging Face OCR engines).

Used when ``settings.OCR_ENGINE`` selects a Hugging Face model. Emits dicts
in the same shape as ``gradeops.rubric_engine.pdf_ocr.extract_from_pdfs`` so
the downstream grading code is engine-agnostic.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

_FILENAME_RE = re.compile(
    r"^(?P<sid>[A-Za-z0-9-]+)(?:_(?P<qid>Q[A-Za-z0-9-]+))?\.pdf$",
    re.IGNORECASE,
)


def _parse_name(name: str) -> tuple[str | None, str | None]:
    m = _FILENAME_RE.match(Path(name).name)
    if not m:
        return None, None
    return m.group("sid"), m.group("qid")


async def extract_via_ml_worker(
    pdfs: list[tuple[str, bytes]],
    engine: str,
    rubric: dict,
) -> list[dict]:
    """Run OCR on each PDF via the ml-worker; emit per-(student, question) dicts.

    Per-question PDFs (filename ``STU001_Q1.pdf``): all pages join into one
    answer keyed by the parsed question_id.

    Per-student PDFs (filename ``STU001.pdf``): page *i* maps to the *i*-th
    question in the rubric's declared order.
    """
    settings = get_settings()
    base = settings.ML_WORKER_URL.rstrip("/")
    rubric_qids = [
        str(q.get("question_id", ""))
        for q in (rubric.get("questions") or [])
    ]

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=600) as client:
        for filename, pdf_bytes in pdfs:
            sid, qid_in_name = _parse_name(filename)
            student_id = sid or "UNKNOWN"
            try:
                resp = await client.post(
                    f"{base}/ocr/{engine}",
                    files={"file": (filename, pdf_bytes, "application/pdf")},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                out.append(
                    {"filename": filename, "error": f"{type(exc).__name__}: {exc}"}
                )
                continue

            pages: list[str] = data.get("pages") or []
            conf = float(data.get("confidence", 0.5))

            if qid_in_name:
                out.append(
                    {
                        "filename": filename,
                        "student_id": student_id,
                        "question_id": qid_in_name,
                        "text": str(data.get("text", "")),
                        "ocr_confidence": conf,
                    }
                )
            else:
                for i, page_text in enumerate(pages):
                    if i >= len(rubric_qids):
                        break
                    out.append(
                        {
                            "filename": filename,
                            "student_id": student_id,
                            "question_id": rubric_qids[i],
                            "text": page_text,
                            "ocr_confidence": conf,
                        }
                    )
    return out
