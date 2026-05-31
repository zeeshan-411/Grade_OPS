from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExamCreate(BaseModel):
    """Body for POST /api/v1/exams. Rubric is the full JSON the instructor uploaded."""

    rubric: dict[str, Any] = Field(..., description="Full rubric JSON document")


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_id: str
    course: str
    title: str
    owner_id: uuid.UUID
    created_at: datetime
    pdf_count: int = 0


class ExamDetail(ExamOut):
    rubric_json: dict[str, Any]


class ExamPdfOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    student_id: str | None
    question_id: str | None
    size_bytes: int
    uploaded_by_id: uuid.UUID
    created_at: datetime


class PdfUploadSummary(BaseModel):
    uploaded: list[ExamPdfOut]
    rejected: list[dict[str, str]]
