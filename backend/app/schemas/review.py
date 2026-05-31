from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.review import ReviewAction


class ReviewIn(BaseModel):
    question_id: str = Field(..., max_length=64)
    action: ReviewAction
    override_score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    id: uuid.UUID
    student_grade_id: uuid.UUID
    question_id: str
    reviewed_by_id: uuid.UUID
    reviewed_by_email: str
    action: ReviewAction
    override_score: float | None
    comment: str | None
    created_at: datetime


class PlagiarismPartner(BaseModel):
    student_id: str
    score: float


class ReviewQueueItem(BaseModel):
    grade_id: uuid.UUID
    student_id: str
    question_id: str
    ai_score: float
    max_marks: float
    ai_verified: bool
    ai_summary: str
    ai_flags: list[str]
    ai_criteria: list[dict]
    pdf_id: uuid.UUID | None
    pdf_filename: str | None
    pdf_page: int | None
    review: ReviewOut | None
    plagiarism_partners: list[PlagiarismPartner]
