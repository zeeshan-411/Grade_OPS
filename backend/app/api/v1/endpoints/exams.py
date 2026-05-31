from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.exam import Exam, ExamPdf
from app.models.grading import GradingRun, RunStatus, StudentGrade
from app.models.plagiarism import PlagiarismPair
from app.models.user import Role, User
from app.schemas.exam import (
    ExamCreate,
    ExamDetail,
    ExamOut,
    ExamPdfOut,
    PdfUploadSummary,
)
from app.schemas.grading import GradeSummary, GradingRunOut, StudentGradeOut
from app.schemas.plagiarism import PlagiarismPairOut
from app.services.demo_grading import synthesize_demo_grades
from app.services.grading import run_grading_pipeline
from app.services.plagiarism import compute_pairs_from_text, synthesize_pairs
from app.services.storage import delete_pdf, get_storage, pdf_key

log = logging.getLogger(__name__)

router = APIRouter(prefix="/exams", tags=["exams"])

# Accepts:
#   STU001.pdf            → ("STU001", None)   — per-student (all questions in one file)
#   STU001_Q1.pdf         → ("STU001", "Q1")   — per-question (legacy)
_FILENAME_RE = re.compile(
    r"^(?P<sid>[A-Za-z0-9-]+)(?:_(?P<qid>Q[A-Za-z0-9-]+))?\.pdf$",
    re.IGNORECASE,
)


def _parse_filename(name: str) -> tuple[str, str | None] | None:
    m = _FILENAME_RE.match(Path(name).name)
    if not m:
        return None
    return m.group("sid"), m.group("qid")


async def _exam_or_404(db: AsyncSession, exam_id: uuid.UUID) -> Exam:
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalar_one_or_none()
    if exam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")
    return exam


# ──────────────────────────────────────────────────────────────────────────
# Exam CRUD
# ──────────────────────────────────────────────────────────────────────────


@router.post("", response_model=ExamOut, status_code=status.HTTP_201_CREATED)
async def create_exam(
    payload: ExamCreate,
    user: Annotated[User, Depends(require_role(Role.INSTRUCTOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExamOut:
    """Instructor uploads a rubric JSON. The rubric must include `exam_id`, `course`, `title`."""
    rubric = payload.rubric
    missing = [k for k in ("exam_id", "course") if not rubric.get(k)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rubric is missing required fields: {missing}",
        )

    exam = Exam(
        exam_id=str(rubric["exam_id"]),
        course=str(rubric["course"]),
        title=str(rubric.get("title") or rubric["exam_id"]),
        rubric_json=rubric,
        owner_id=user.id,
    )
    db.add(exam)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An exam with exam_id={rubric['exam_id']!r} already exists",
        ) from exc
    await db.refresh(exam)
    return ExamOut(
        id=exam.id,
        exam_id=exam.exam_id,
        course=exam.course,
        title=exam.title,
        owner_id=exam.owner_id,
        created_at=exam.created_at,
        pdf_count=0,
    )


@router.get("", response_model=list[ExamOut])
async def list_exams(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ExamOut]:
    pdf_count = (
        select(ExamPdf.exam_fk, func.count(ExamPdf.id).label("n"))
        .group_by(ExamPdf.exam_fk)
        .subquery()
    )
    stmt = (
        select(Exam, func.coalesce(pdf_count.c.n, 0))
        .outerjoin(pdf_count, pdf_count.c.exam_fk == Exam.id)
        .order_by(Exam.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        ExamOut(
            id=exam.id,
            exam_id=exam.exam_id,
            course=exam.course,
            title=exam.title,
            owner_id=exam.owner_id,
            created_at=exam.created_at,
            pdf_count=int(n or 0),
        )
        for exam, n in rows
    ]


@router.get("/{exam_id}", response_model=ExamDetail)
async def get_exam(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExamDetail:
    exam = await _exam_or_404(db, exam_id)
    count_stmt = select(func.count(ExamPdf.id)).where(ExamPdf.exam_fk == exam.id)
    n = (await db.execute(count_stmt)).scalar_one()
    return ExamDetail(
        id=exam.id,
        exam_id=exam.exam_id,
        course=exam.course,
        title=exam.title,
        owner_id=exam.owner_id,
        created_at=exam.created_at,
        rubric_json=exam.rubric_json,
        pdf_count=int(n),
    )


# ──────────────────────────────────────────────────────────────────────────
# PDF upload (both roles)
# ──────────────────────────────────────────────────────────────────────────


@router.post(
    "/{exam_id}/pdfs",
    response_model=PdfUploadSummary,
    status_code=status.HTTP_201_CREATED,
)
async def upload_pdfs(
    exam_id: uuid.UUID,
    files: Annotated[list[UploadFile], File(..., description="One or more student PDFs")],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PdfUploadSummary:
    exam = await _exam_or_404(db, exam_id)
    storage = get_storage()

    uploaded: list[ExamPdf] = []
    rejected: list[dict[str, str]] = []

    for upload in files:
        if not upload.filename:
            rejected.append({"filename": "(no name)", "reason": "missing filename"})
            continue
        if not upload.filename.lower().endswith(".pdf"):
            rejected.append({"filename": upload.filename, "reason": "not a .pdf"})
            continue

        parsed = _parse_filename(upload.filename)
        student_id, question_id = (parsed if parsed else (None, None))

        content = await upload.read()
        pdf_id = uuid.uuid4()
        key = pdf_key(exam.id, pdf_id)
        storage.put(key, content)

        row = ExamPdf(
            id=pdf_id,
            exam_fk=exam.id,
            uploaded_by_id=user.id,
            filename=upload.filename,
            student_id=student_id,
            question_id=question_id,
            file_path=key,
            size_bytes=len(content),
        )
        db.add(row)
        uploaded.append(row)

    await db.commit()
    for row in uploaded:
        await db.refresh(row)

    return PdfUploadSummary(
        uploaded=[ExamPdfOut.model_validate(r) for r in uploaded],
        rejected=rejected,
    )


@router.get("/{exam_id}/pdfs", response_model=list[ExamPdfOut])
async def list_pdfs(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ExamPdfOut]:
    await _exam_or_404(db, exam_id)
    stmt = (
        select(ExamPdf)
        .where(ExamPdf.exam_fk == exam_id)
        .order_by(ExamPdf.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [ExamPdfOut.model_validate(r) for r in rows]


@router.delete("/{exam_id}/pdfs", status_code=status.HTTP_200_OK)
async def clear_pdfs(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    """Remove every uploaded PDF for the exam (files on disk + DB rows)."""
    await _exam_or_404(db, exam_id)
    rows = (
        await db.execute(select(ExamPdf).where(ExamPdf.exam_fk == exam_id))
    ).scalars().all()
    deleted = 0
    for row in rows:
        delete_pdf(row.file_path)
        await db.delete(row)
        deleted += 1
    await db.commit()
    return {"deleted": deleted}


@router.delete("/{exam_id}/grades", status_code=status.HTTP_200_OK)
async def clear_grades(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(require_role(Role.INSTRUCTOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    """Delete every grading run for this exam.

    Cascades through student_grades → grade_reviews and plagiarism_pairs (all
    have ON DELETE CASCADE on their run/grade FKs). PDFs and the exam itself
    are kept intact so a fresh grading run can be started.
    """
    await _exam_or_404(db, exam_id)
    runs = (
        await db.execute(select(GradingRun).where(GradingRun.exam_fk == exam_id))
    ).scalars().all()
    deleted = 0
    for run in runs:
        await db.delete(run)
        deleted += 1
    await db.commit()
    return {"deleted_runs": deleted}


@router.delete("/{exam_id}", status_code=status.HTTP_200_OK)
async def delete_exam(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(require_role(Role.INSTRUCTOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Delete an exam and everything it owns.

    Cascades through every dependent table (exam_pdfs, grading_runs,
    student_grades, grade_reviews, plagiarism_pairs). Also removes the exam's
    PDF directory from disk.
    """
    exam = await _exam_or_404(db, exam_id)

    # Remove PDF objects from storage before nuking the DB rows.
    get_storage().delete_prefix(f"exams/{exam.id}")

    await db.delete(exam)
    await db.commit()
    return {"deleted": str(exam_id)}


# ──────────────────────────────────────────────────────────────────────────
# Grading
# ──────────────────────────────────────────────────────────────────────────


def _flag_check(payload: dict) -> tuple[bool, bool]:
    """Return (needs_review, verified) from a StudentExamGrade dump."""
    flags = payload.get("flags", []) or []
    needs_review = "NEEDS_REVIEW" in flags
    verified = any("VERIFIED" in f for f in flags)
    return needs_review, verified


async def _build_summary(
    db: AsyncSession, exam_id: uuid.UUID
) -> GradeSummary | None:
    """Return the latest grading run + its student grades for an exam, or None."""
    run_stmt = (
        select(GradingRun)
        .where(GradingRun.exam_fk == exam_id)
        .order_by(GradingRun.started_at.desc())
        .limit(1)
    )
    run = (await db.execute(run_stmt)).scalar_one_or_none()
    if run is None:
        return None

    grade_stmt = (
        select(StudentGrade)
        .where(StudentGrade.run_fk == run.id)
        .order_by(StudentGrade.student_id)
    )
    grades = (await db.execute(grade_stmt)).scalars().all()

    total_score = sum(g.total_score for g in grades)
    max_possible = sum(g.max_possible for g in grades)
    return GradeSummary(
        run=GradingRunOut.model_validate(run),
        grades=[StudentGradeOut.model_validate(g) for g in grades],
        total_students=len(grades),
        total_score=total_score,
        max_possible=max_possible,
        needs_review=sum(1 for g in grades if g.needs_review),
        verified=sum(1 for g in grades if g.verified),
    )


@router.post("/{exam_id}/grade", response_model=GradeSummary)
async def grade_exam_route(
    exam_id: uuid.UUID,
    user: Annotated[User, Depends(require_role(Role.INSTRUCTOR))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GradeSummary:
    """Instructor triggers a grading run for an exam.

    Loads all uploaded PDFs, runs OCR + LangGraph grading, persists the result,
    and returns a summary. Synchronous — the request blocks until grading
    completes. For large exams, expect minutes.
    """
    settings = get_settings()

    if not settings.DEMO_MODE and not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GEMINI_API_KEY is not configured on the backend.",
        )

    exam = await _exam_or_404(db, exam_id)
    pdfs_stmt = select(ExamPdf).where(ExamPdf.exam_fk == exam_id)
    pdfs = list((await db.execute(pdfs_stmt)).scalars().all())
    if not pdfs and not settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No PDFs uploaded for this exam yet.",
        )

    run = GradingRun(
        exam_fk=exam.id,
        started_by_id=user.id,
        status=RunStatus.RUNNING,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    extractions: list[dict] = []
    try:
        if settings.DEMO_MODE:
            payloads, stats = await synthesize_demo_grades(exam, pdfs)
        else:
            payloads, stats, extractions = await run_grading_pipeline(exam, pdfs)
    except Exception as exc:  # noqa: BLE001
        log.exception("grading pipeline failed for exam %s", exam_id)
        run.status = RunStatus.FAILED
        run.error_msg = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Grading failed: {type(exc).__name__}: {exc}",
        ) from exc

    for payload in payloads:
        needs_review, verified = _flag_check(payload)
        db.add(
            StudentGrade(
                exam_fk=exam.id,
                run_fk=run.id,
                student_id=str(payload.get("student_id", "")),
                total_score=float(payload.get("total_score", 0.0)),
                max_possible=float(payload.get("max_possible", 0.0)),
                needs_review=needs_review,
                verified=verified,
                flags=payload.get("flags", []) or [],
                payload=payload,
            )
        )

    # Real similarity over OCR-extracted text when available; synthetic pairs
    # only when there's no extracted text (DEMO_MODE, or every OCR call failed).
    if extractions:
        pair_dicts = compute_pairs_from_text(extractions)
    else:
        pair_dicts = synthesize_pairs(
            [str(p.get("student_id", "")) for p in payloads],
            [
                str(q.get("question_id", ""))
                for p in payloads
                for q in (p.get("question_grades") or [])
            ],
        )

    for pair in pair_dicts:
        db.add(
            PlagiarismPair(
                exam_fk=exam.id,
                run_fk=run.id,
                question_id=pair["question_id"],
                student_a=pair["student_a"],
                student_b=pair["student_b"],
                score=pair["score"],
            )
        )

    run.status = RunStatus.DONE
    run.n_students = stats["n_students"]
    run.n_pdfs = stats["n_pdfs"]
    run.finished_at = datetime.now(timezone.utc)
    await db.commit()

    summary = await _build_summary(db, exam.id)
    assert summary is not None
    return summary


@router.get("/{exam_id}/grades", response_model=GradeSummary | None)
async def get_grades(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GradeSummary | None:
    await _exam_or_404(db, exam_id)
    return await _build_summary(db, exam_id)


@router.get("/{exam_id}/runs", response_model=list[GradingRunOut])
async def list_runs(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GradingRunOut]:
    await _exam_or_404(db, exam_id)
    stmt = (
        select(GradingRun)
        .where(GradingRun.exam_fk == exam_id)
        .order_by(GradingRun.started_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [GradingRunOut.model_validate(r) for r in rows]


@router.get("/{exam_id}/plagiarism", response_model=list[PlagiarismPairOut])
async def list_plagiarism(
    exam_id: uuid.UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlagiarismPairOut]:
    """Suspicious pairs from the latest grading run, highest score first."""
    await _exam_or_404(db, exam_id)
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
    rows = (
        await db.execute(
            select(PlagiarismPair)
            .where(PlagiarismPair.run_fk == latest_run.id)
            .order_by(PlagiarismPair.score.desc())
        )
    ).scalars().all()
    return [PlagiarismPairOut.model_validate(r) for r in rows]
