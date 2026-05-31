from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.exam import Exam, ExamPdf
from app.models.grading import GradingRun, StudentGrade
from app.models.plagiarism import PlagiarismPair
from app.models.review import GradeReview, ReviewAction
from app.models.user import Role, User
from app.schemas.review import (
    PlagiarismPartner,
    ReviewIn,
    ReviewOut,
    ReviewQueueItem,
)
from app.services.storage import read_pdf_bytes

router = APIRouter(tags=["reviews"])


async def _exam_or_404(db: AsyncSession, exam_id: uuid.UUID) -> Exam:
    exam = (
        await db.execute(select(Exam).where(Exam.id == exam_id))
    ).scalar_one_or_none()
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")
    return exam


def _to_review_out(r: GradeReview, email: str) -> ReviewOut:
    return ReviewOut(
        id=r.id,
        student_grade_id=r.student_grade_id,
        question_id=r.question_id,
        reviewed_by_id=r.reviewed_by_id,
        reviewed_by_email=email,
        action=r.action,
        override_score=r.override_score,
        comment=r.comment,
        created_at=r.created_at,
    )


# ──────────────────────────────────────────────────────────────────────────
# Queue — every (student, question) pair from the latest grading run, with
# the AI grade and any existing TA review attached.
# ──────────────────────────────────────────────────────────────────────────


@router.get("/exams/{exam_id}/review/queue", response_model=list[ReviewQueueItem])
async def review_queue(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ReviewQueueItem]:
    exam = await _exam_or_404(db, exam_id)

    # 1-based page index per question, derived from the rubric. Generated
    # sample PDFs put answers in this order (one page per question) so the
    # review iframe can scroll directly via #page=N.
    question_order: dict[str, int] = {
        str(q.get("question_id", "")): i + 1
        for i, q in enumerate((exam.rubric_json or {}).get("questions") or [])
    }

    latest_run = (
        await db.execute(
            select(GradingRun)
            .where(GradingRun.exam_fk == exam_id)
            .order_by(GradingRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_run is None:
        return []

    grades = list(
        (
            await db.execute(
                select(StudentGrade)
                .where(StudentGrade.run_fk == latest_run.id)
                .order_by(StudentGrade.student_id)
            )
        ).scalars().all()
    )
    if not grades:
        return []

    grade_ids = [g.id for g in grades]
    reviews = list(
        (
            await db.execute(
                select(GradeReview, User.email)
                .join(User, User.id == GradeReview.reviewed_by_id)
                .where(GradeReview.student_grade_id.in_(grade_ids))
            )
        ).all()
    )
    review_by_key: dict[tuple[uuid.UUID, str], tuple[GradeReview, str]] = {
        (r.student_grade_id, r.question_id): (r, email) for r, email in reviews
    }

    pdfs = list(
        (
            await db.execute(select(ExamPdf).where(ExamPdf.exam_fk == exam_id))
        ).scalars().all()
    )
    # Two-tier index: specific per-question file wins, otherwise fall back to
    # the student's umbrella PDF (one PDF holding all that student's answers).
    pdf_by_pair: dict[tuple[str, str], ExamPdf] = {
        (p.student_id, p.question_id): p
        for p in pdfs
        if p.student_id and p.question_id
    }
    pdf_by_student: dict[str, ExamPdf] = {
        p.student_id: p
        for p in pdfs
        if p.student_id and not p.question_id
    }

    # Map (student_id, question_id) → [partners with score]
    pairs = list(
        (
            await db.execute(
                select(PlagiarismPair).where(PlagiarismPair.run_fk == latest_run.id)
            )
        ).scalars().all()
    )
    partners_by_key: dict[tuple[str, str], list[PlagiarismPartner]] = {}
    for p in pairs:
        partners_by_key.setdefault((p.student_a, p.question_id), []).append(
            PlagiarismPartner(student_id=p.student_b, score=p.score)
        )
        partners_by_key.setdefault((p.student_b, p.question_id), []).append(
            PlagiarismPartner(student_id=p.student_a, score=p.score)
        )

    items: list[ReviewQueueItem] = []
    for g in grades:
        for q in g.payload.get("question_grades", []) or []:
            qid = str(q.get("question_id", ""))
            pdf = pdf_by_pair.get((g.student_id, qid)) or pdf_by_student.get(g.student_id)
            review_tuple = review_by_key.get((g.id, qid))
            review_out = (
                _to_review_out(review_tuple[0], review_tuple[1]) if review_tuple else None
            )
            if pdf is None:
                pdf_page = None
            elif pdf.question_id:
                # Legacy single-page per-question file
                pdf_page = 1
            else:
                # Per-student multi-page PDF: jump to the question's page
                pdf_page = question_order.get(qid)

            items.append(
                ReviewQueueItem(
                    grade_id=g.id,
                    student_id=g.student_id,
                    question_id=qid,
                    ai_score=float(q.get("total_marks", 0) or 0),
                    max_marks=float(q.get("max_marks", 0) or 0),
                    ai_verified=bool(q.get("verified", False)),
                    ai_summary=str(q.get("summary", "")),
                    ai_flags=list(q.get("flags", []) or []),
                    ai_criteria=list(q.get("criterion_results", []) or []),
                    pdf_id=pdf.id if pdf else None,
                    pdf_filename=pdf.filename if pdf else None,
                    pdf_page=pdf_page,
                    review=review_out,
                    plagiarism_partners=partners_by_key.get((g.student_id, qid), []),
                )
            )
    return items


# ──────────────────────────────────────────────────────────────────────────
# Submit a review (TA only). Upserts on (student_grade_id, question_id).
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/grades/{grade_id}/review",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    grade_id: uuid.UUID,
    payload: ReviewIn,
    user: Annotated[User, Depends(require_role(Role.TA))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReviewOut:
    grade = (
        await db.execute(select(StudentGrade).where(StudentGrade.id == grade_id))
    ).scalar_one_or_none()
    if grade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found"
        )

    # Verify the question_id actually exists on this grade.
    qids = {
        str(q.get("question_id", ""))
        for q in (grade.payload.get("question_grades", []) or [])
    }
    if payload.question_id not in qids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"question_id {payload.question_id!r} is not part of this grade",
        )

    if payload.action == ReviewAction.OVERRIDE and payload.override_score is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OVERRIDE requires override_score",
        )

    existing = (
        await db.execute(
            select(GradeReview).where(
                GradeReview.student_grade_id == grade_id,
                GradeReview.question_id == payload.question_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        review = GradeReview(
            student_grade_id=grade_id,
            question_id=payload.question_id,
            reviewed_by_id=user.id,
            action=payload.action,
            override_score=payload.override_score
            if payload.action == ReviewAction.OVERRIDE
            else None,
            comment=payload.comment,
        )
        db.add(review)
    else:
        existing.action = payload.action
        existing.reviewed_by_id = user.id
        existing.override_score = (
            payload.override_score if payload.action == ReviewAction.OVERRIDE else None
        )
        existing.comment = payload.comment
        review = existing

    await db.commit()
    await db.refresh(review)
    return _to_review_out(review, user.email)


# ──────────────────────────────────────────────────────────────────────────
# Serve a PDF binary so the review UI can render the source page next to the
# AI grade.
# ──────────────────────────────────────────────────────────────────────────


@router.get("/exams/{exam_id}/pdfs/{pdf_id}/file")
async def serve_pdf(
    exam_id: uuid.UUID,
    pdf_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    pdf = (
        await db.execute(
            select(ExamPdf).where(ExamPdf.id == pdf_id, ExamPdf.exam_fk == exam_id)
        )
    ).scalar_one_or_none()
    if pdf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF not found")

    try:
        content = read_pdf_bytes(pdf.file_path)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PDF object missing: {exc}",
        ) from exc

    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{pdf.filename}"'},
    )
