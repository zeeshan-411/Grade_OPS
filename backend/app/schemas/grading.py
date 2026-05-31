from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.grading import RunStatus


class GradingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_fk: uuid.UUID
    started_by_id: uuid.UUID
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    error_msg: str | None
    n_students: int | None
    n_pdfs: int | None


class StudentGradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_fk: uuid.UUID
    student_id: str
    total_score: float
    max_possible: float
    needs_review: bool
    verified: bool
    flags: list[str]
    payload: dict[str, Any]
    created_at: datetime


class GradeSummary(BaseModel):
    run: GradingRunOut
    grades: list[StudentGradeOut]
    total_students: int
    total_score: float
    max_possible: float
    needs_review: int
    verified: int
