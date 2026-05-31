"""Pydantic models for the GradeOps Rubric Engine."""
from __future__ import annotations

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Rubric Input Models
# ─────────────────────────────────────────────────────────────────────────────


class Criterion(BaseModel):
    id: str
    description: str
    marks: float
    partial_credit: str | None = None


class Deduction(BaseModel):
    condition: str
    penalty: float


class AlternativeAnswer(BaseModel):
    description: str
    instruction: str


class Question(BaseModel):
    question_id: str
    question_text: str
    max_marks: float
    criteria: list[Criterion]
    deductions: list[Deduction] = Field(default_factory=list)
    alternatives: list[AlternativeAnswer] = Field(default_factory=list)
    grader_notes: str | None = None


class GlobalPolicies(BaseModel):
    partial_credit: bool = True
    ocr_confidence_floor: float = 0.6
    abstain_policy: str = (
        "If the extracted text is unreadable or empty, assign 0 marks to all "
        "criteria and set flag UNREADABLE."
    )


class ExamRubric(BaseModel):
    exam_id: str
    course: str
    total_marks: float
    policies: GlobalPolicies = Field(default_factory=GlobalPolicies)
    questions: list[Question]


# ─────────────────────────────────────────────────────────────────────────────
# Grade Output Models
# ─────────────────────────────────────────────────────────────────────────────


class CriterionResult(BaseModel):
    criterion_id: str
    marks_awarded: float
    justification: str


class DeductionResult(BaseModel):
    condition: str
    applied: bool
    penalty: float


class QuestionGrade(BaseModel):
    student_id: str
    question_id: str
    criterion_results: list[CriterionResult]
    deduction_results: list[DeductionResult]
    total_marks: float
    max_marks: float
    summary: str
    flags: list[str] = Field(default_factory=list)
    verified: bool = False


class StudentExamGrade(BaseModel):
    student_id: str
    exam_id: str
    question_grades: list[QuestionGrade]
    total_score: float
    max_possible: float
    flags: list[str] = Field(default_factory=list)
