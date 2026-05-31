"""Aggregator module so Alembic can discover all models via Base.metadata."""
from __future__ import annotations

from app.db.base_class import Base  # noqa: F401
from app.models.exam import Exam, ExamPdf  # noqa: F401
from app.models.grading import GradingRun, StudentGrade  # noqa: F401
from app.models.plagiarism import PlagiarismPair  # noqa: F401
from app.models.review import GradeReview  # noqa: F401
from app.models.user import User  # noqa: F401
