"""Deterministic grade synthesizer for demos.

When DEMO_MODE is on the /grade endpoint calls synthesize_demo_grades instead
of run_grading_pipeline. It produces output that matches the shape the real
LangGraph pipeline emits, so the frontend renders identically. No OCR, no LLM,
no quota usage.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from app.models.exam import Exam, ExamPdf


def _seed(*parts: str) -> float:
    """Deterministic float in [0, 1) from a tuple of strings."""
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _justification(c: dict[str, Any], pct: float) -> str:
    cond = c.get("condition") or c.get("criterion_id") or "criterion"
    if pct >= 0.9:
        return f"Solution satisfies '{cond}' — all key steps shown."
    if pct >= 0.7:
        return f"Largely correct on '{cond}'; minor steps missing or rushed."
    if pct >= 0.5:
        return f"Partial credit: concept identified for '{cond}' but execution incomplete."
    return f"Significant gaps in '{cond}' — recommend manual review."


async def synthesize_demo_grades(
    exam: Exam, pdfs: list[ExamPdf]
) -> tuple[list[dict], dict]:
    """Return (payloads, stats) matching run_grading_pipeline's contract.

    student_ids come from parsed PDFs when available; otherwise seeds three
    stub students so the demo still has something to show. Adds a short delay
    so the UI shows the "Grading…" state instead of snapping instantly to
    results.
    """
    rubric = exam.rubric_json or {}
    questions = rubric.get("questions") or []

    student_ids = sorted({p.student_id for p in pdfs if p.student_id})
    if not student_ids:
        student_ids = ["STU001", "STU002", "STU003"]

    # Pretend we're crunching OCR + LLM calls. Cap to 12s so demos don't drag.
    await asyncio.sleep(min(12.0, 2.0 + 1.5 * len(student_ids)))

    payloads: list[dict] = []
    for sid in student_ids:
        question_grades: list[dict] = []
        for q in questions:
            qid = str(q.get("question_id", ""))
            q_max = float(q.get("max_marks", 0) or 0)
            criteria = q.get("criteria") or []

            crit_results: list[dict] = []
            running_total = 0
            for c in criteria:
                cid = str(c.get("criterion_id", ""))
                c_max = float(c.get("marks", 0) or 0)
                pct = 0.55 + 0.45 * _seed(sid, qid, cid)
                mark = int(round(c_max * pct))
                running_total += mark
                crit_results.append(
                    {
                        "criterion_id": cid,
                        "marks_awarded": float(mark),
                        "justification": _justification(c, pct),
                    }
                )

            q_total = min(running_total, int(q_max)) if q_max else running_total
            verified = _seed(sid, qid, "verify") > 0.25
            q_flags = ["VERIFIED_APPROVED"] if verified else ["NEEDS_REVIEW"]

            deductions_meta = q.get("deductions") or []
            ded_results = [
                {
                    "condition": str(d.get("condition", "")),
                    "penalty": float(d.get("penalty", 0) or 0),
                    "applied": False,
                }
                for d in deductions_meta
            ]

            question_grades.append(
                {
                    "question_id": qid,
                    "total_marks": float(q_total),
                    "max_marks": float(int(q_max)),
                    "verified": verified,
                    "flags": q_flags,
                    "summary": "Demo grade synthesized from rubric (no LLM call).",
                    "criterion_results": crit_results,
                    "deduction_results": ded_results,
                }
            )

        total_score = float(sum(int(q["total_marks"]) for q in question_grades))
        max_possible = float(sum(int(q["max_marks"]) for q in question_grades))

        student_flags: list[str] = []
        if any("NEEDS_REVIEW" in q["flags"] for q in question_grades):
            student_flags.append("NEEDS_REVIEW")
        if all(q["verified"] for q in question_grades) and question_grades:
            student_flags.append("VERIFIED_APPROVED")

        payloads.append(
            {
                "student_id": sid,
                "total_score": total_score,
                "max_possible": max_possible,
                "flags": student_flags,
                "question_grades": question_grades,
            }
        )

    return payloads, {"n_students": len(payloads), "n_pdfs": len(pdfs)}
