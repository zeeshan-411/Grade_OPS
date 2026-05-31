"""Service layer that calls the gradeops grading pipeline.

This module isolates the heavy imports (langgraph, langchain, pymupdf) so we
can swap engines later without touching the API layer.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings
from app.models.exam import Exam, ExamPdf
from app.services.storage import read_pdf_bytes

log = logging.getLogger(__name__)


async def run_grading_pipeline(
    exam: Exam, pdfs: list[ExamPdf], *, ocr_dpi: int = 200, max_concurrency: int = 2
) -> tuple[list[dict], dict, list[dict]]:
    """Run OCR → LangGraph grading on every PDF tied to an exam.

    OCR engine is selected by ``settings.OCR_ENGINE``:
      * ``gemini`` — Google Gemini Vision via gradeops
      * ``nougat`` — facebook/nougat-small via the ml-worker container

    Returns:
        (student_grade_payloads, run_stats, extractions):
            student_grade_payloads — list of StudentExamGrade.model_dump() dicts,
                each with an extra ``extracted_text`` key: {question_id: text}
            run_stats — {"n_students": int, "n_pdfs": int}
            extractions — flat per-(student, question) OCR records suitable for
                feeding into ``compute_pairs_from_text``
    """
    # Imports are deferred so the FastAPI app starts even if these are missing.
    from gradeops.rubric_engine import grade_exam
    from gradeops.rubric_engine import grading_agent as _ga
    from gradeops.rubric_engine.pdf_ocr import extract_from_pdfs, group_by_student
    from gradeops.rubric_engine.schema import ExamRubric

    rubric = ExamRubric.model_validate(exam.rubric_json)
    settings = get_settings()

    pending: list[tuple[str, bytes]] = []
    for p in pdfs:
        try:
            pending.append((p.filename, read_pdf_bytes(p.file_path)))
        except OSError as exc:
            log.warning("could not read pdf %s: %s", p.file_path, exc)

    if not pending:
        return [], {"n_students": 0, "n_pdfs": 0}, []

    engine = settings.OCR_ENGINE.lower()
    if engine == "nougat":
        from app.services.ocr_client import extract_via_ml_worker

        log.info("OCR via ml-worker (nougat) for %d PDFs", len(pending))
        extractions = await extract_via_ml_worker(
            pending,
            engine="nougat",
            rubric=exam.rubric_json or {},
        )
    else:
        log.info("OCR via gemini for %d PDFs", len(pending))
        extractions = await extract_from_pdfs(
            pending,
            llm=_ga.llm,
            engine="gemini",
            dpi=ocr_dpi,
            max_concurrency=max_concurrency,
        )

    good_extractions = [e for e in extractions if "error" not in e]
    student_answers = group_by_student(good_extractions)
    if not student_answers:
        return [], {"n_students": 0, "n_pdfs": len(pending)}, good_extractions

    student_grades = await grade_exam(
        rubric,
        student_answers,
        max_concurrency=max_concurrency,
    )

    text_by_student: dict[str, dict[str, str]] = {}
    for ext in good_extractions:
        sid = str(ext.get("student_id", ""))
        qid = str(ext.get("question_id", ""))
        if not sid or not qid:
            continue
        text_by_student.setdefault(sid, {})[qid] = str(ext.get("text", "") or "")

    payloads = []
    for g in student_grades:
        payload = g.model_dump(mode="json")
        payload["extracted_text"] = text_by_student.get(g.student_id, {})
        payloads.append(payload)

    return (
        payloads,
        {"n_students": len(student_grades), "n_pdfs": len(pending)},
        good_extractions,
    )
