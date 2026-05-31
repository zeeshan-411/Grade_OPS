"""Rubric loader, validator, and normalizer."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .schema import ExamRubric

MARKS_TOLERANCE = 0.01


def load_rubric(path: str | Path) -> ExamRubric:
    """Load JSON, parse into ExamRubric.

    Raises FileNotFoundError if the path does not exist, json.JSONDecodeError
    on invalid JSON, and pydantic.ValidationError on schema mismatch.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Rubric file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return ExamRubric.model_validate(data)


def validate_rubric(rubric: ExamRubric) -> list[str]:
    """Return a list of human-readable warning strings.

    Checks performed:
    - Criteria marks don't sum to question max_marks.
    - Question max_marks don't sum to exam total_marks.
    - Criterion with marks > 2 has no partial_credit instruction.
    - Duplicate criterion IDs (within question and across exam).
    """
    warnings: list[str] = []
    all_criterion_ids: list[str] = []

    for q in rubric.questions:
        criterion_sum = sum(c.marks for c in q.criteria)
        if not math.isclose(criterion_sum, q.max_marks, abs_tol=MARKS_TOLERANCE):
            warnings.append(
                f"Question {q.question_id}: criteria marks sum to {criterion_sum} "
                f"but max_marks is {q.max_marks}"
            )

        seen_ids: set[str] = set()
        for c in q.criteria:
            if c.id in seen_ids:
                warnings.append(
                    f"Question {q.question_id}: duplicate criterion ID {c.id!r}"
                )
            seen_ids.add(c.id)
            all_criterion_ids.append(c.id)

            if c.marks > 2 and not c.partial_credit:
                warnings.append(
                    f"Criterion {c.id} (marks={c.marks}) has no partial_credit "
                    "instruction — graders may award marks inconsistently"
                )

    question_sum = sum(q.max_marks for q in rubric.questions)
    if not math.isclose(question_sum, rubric.total_marks, abs_tol=MARKS_TOLERANCE):
        warnings.append(
            f"Exam {rubric.exam_id}: questions max_marks sum to {question_sum} "
            f"but total_marks is {rubric.total_marks}"
        )

    # Cross-question duplicate IDs
    duplicates = {cid for cid in all_criterion_ids if all_criterion_ids.count(cid) > 1}
    seen_dupes: set[str] = set()
    for cid in duplicates:
        if cid in seen_dupes:
            continue
        seen_dupes.add(cid)
        warnings.append(f"Duplicate criterion ID across exam: {cid!r}")

    return warnings


def normalize_rubric(rubric: ExamRubric) -> ExamRubric:
    """Return a normalized copy of the rubric.

    - Strips whitespace from string fields.
    - Deduplicates criterion IDs by appending a numeric suffix to collisions.
    """
    data = rubric.model_dump()

    data["exam_id"] = data["exam_id"].strip()
    data["course"] = data["course"].strip()

    seen_ids: dict[str, int] = {}
    for q in data["questions"]:
        q["question_id"] = q["question_id"].strip()
        q["question_text"] = q["question_text"].strip()
        if q.get("grader_notes"):
            q["grader_notes"] = q["grader_notes"].strip()

        for c in q["criteria"]:
            original_id = c["id"].strip()
            c["description"] = c["description"].strip()
            if c.get("partial_credit"):
                c["partial_credit"] = c["partial_credit"].strip()

            if original_id in seen_ids:
                seen_ids[original_id] += 1
                c["id"] = f"{original_id}_{seen_ids[original_id]}"
            else:
                seen_ids[original_id] = 1
                c["id"] = original_id

        for d in q["deductions"]:
            d["condition"] = d["condition"].strip()
        for a in q["alternatives"]:
            a["description"] = a["description"].strip()
            a["instruction"] = a["instruction"].strip()

    return ExamRubric.model_validate(data)
