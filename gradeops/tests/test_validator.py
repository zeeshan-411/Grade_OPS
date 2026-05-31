"""Tests for the rubric loader, validator, and normalizer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gradeops.rubric_engine.schema import (
    Criterion,
    ExamRubric,
    GlobalPolicies,
    Question,
)
from gradeops.rubric_engine.validator import (
    load_rubric,
    normalize_rubric,
    validate_rubric,
)


SAMPLE_RUBRIC_PATH = Path(__file__).parent.parent / "rubrics" / "sample_rubric.json"


def _make_rubric(**overrides) -> ExamRubric:
    """Construct a minimal valid rubric, optionally overriding any top-level field."""
    base = ExamRubric(
        exam_id="EXAM1",
        course="Test Course",
        total_marks=5,
        policies=GlobalPolicies(),
        questions=[
            Question(
                question_id="Q1",
                question_text="Sample question",
                max_marks=5,
                criteria=[
                    Criterion(id="Q1_C1", description="Some criterion", marks=2),
                    Criterion(id="Q1_C2", description="Another", marks=3, partial_credit="half if X"),
                ],
            )
        ],
    )
    if overrides:
        return base.model_copy(update=overrides)
    return base


def test_sample_rubric_loads_cleanly():
    rubric = load_rubric(SAMPLE_RUBRIC_PATH)
    assert rubric.exam_id == "CS201_midsem_2026"
    assert rubric.total_marks == 23
    assert len(rubric.questions) == 3
    assert rubric.questions[0].question_id == "Q1"
    assert rubric.questions[0].max_marks == 10
    assert len(rubric.questions[0].criteria) == 4


def test_sample_rubric_produces_no_warnings():
    rubric = load_rubric(SAMPLE_RUBRIC_PATH)
    warnings = validate_rubric(rubric)
    assert warnings == [], f"Unexpected warnings: {warnings}"


def test_load_rubric_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_rubric("/nonexistent/path/to/rubric.json")


def test_mismatched_criteria_marks_warns():
    rubric = ExamRubric(
        exam_id="E1",
        course="C",
        total_marks=10,
        questions=[
            Question(
                question_id="Q1",
                question_text="...",
                max_marks=10,
                criteria=[
                    Criterion(id="Q1_C1", description="x", marks=3),
                    Criterion(id="Q1_C2", description="y", marks=3),
                ],
            )
        ],
    )
    warnings = validate_rubric(rubric)
    assert any("criteria marks sum" in w for w in warnings)


def test_question_max_marks_dont_sum_to_exam_total_warns():
    rubric = ExamRubric(
        exam_id="E1",
        course="C",
        total_marks=20,  # claims 20 but questions sum to 5
        questions=[
            Question(
                question_id="Q1",
                question_text="...",
                max_marks=5,
                criteria=[Criterion(id="Q1_C1", description="x", marks=5)],
            )
        ],
    )
    warnings = validate_rubric(rubric)
    assert any("questions max_marks sum" in w for w in warnings)


def test_high_marks_criterion_without_partial_credit_warns():
    rubric = _make_rubric()
    # Q1_C2 has marks=3 with partial_credit set; remove the partial_credit to trigger warning.
    rubric.questions[0].criteria[1].partial_credit = None
    warnings = validate_rubric(rubric)
    assert any("no partial_credit" in w for w in warnings)


def test_duplicate_criterion_ids_warn():
    rubric = ExamRubric(
        exam_id="E1",
        course="C",
        total_marks=5,
        questions=[
            Question(
                question_id="Q1",
                question_text="...",
                max_marks=5,
                criteria=[
                    Criterion(id="Q1_C1", description="x", marks=2),
                    Criterion(id="Q1_C1", description="y", marks=3, partial_credit="rule"),
                ],
            )
        ],
    )
    warnings = validate_rubric(rubric)
    assert any("duplicate criterion ID" in w for w in warnings)


def test_normalize_rubric_deduplicates_ids():
    rubric = ExamRubric(
        exam_id="  E1  ",
        course="C",
        total_marks=5,
        questions=[
            Question(
                question_id="Q1",
                question_text="...",
                max_marks=5,
                criteria=[
                    Criterion(id="Q1_C1", description="x", marks=2),
                    Criterion(id="Q1_C1", description="y", marks=3, partial_credit="rule"),
                ],
            )
        ],
    )
    normalized = normalize_rubric(rubric)
    assert normalized.exam_id == "E1"
    ids = [c.id for c in normalized.questions[0].criteria]
    assert len(set(ids)) == len(ids), f"Expected unique IDs after normalization, got {ids}"
    assert "Q1_C1" in ids
    assert "Q1_C1_2" in ids


def test_normalize_rubric_strips_whitespace():
    rubric = ExamRubric(
        exam_id="E1",
        course=" C ",
        total_marks=5,
        questions=[
            Question(
                question_id=" Q1 ",
                question_text=" hello ",
                max_marks=5,
                criteria=[Criterion(id=" Q1_C1 ", description=" desc ", marks=5)],
            )
        ],
    )
    normalized = normalize_rubric(rubric)
    assert normalized.course == "C"
    assert normalized.questions[0].question_id == "Q1"
    assert normalized.questions[0].question_text == "hello"
    assert normalized.questions[0].criteria[0].id == "Q1_C1"
    assert normalized.questions[0].criteria[0].description == "desc"


def test_load_rubric_accepts_string_path(tmp_path):
    src = json.loads(SAMPLE_RUBRIC_PATH.read_text())
    target = tmp_path / "copy.json"
    target.write_text(json.dumps(src))
    rubric = load_rubric(str(target))
    assert rubric.exam_id == src["exam_id"]
