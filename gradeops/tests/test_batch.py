"""Tests for the batch orchestrator. The grading_agent is mocked at module level."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from gradeops.rubric_engine.batch import grade_exam
from gradeops.rubric_engine.schema import (
    Criterion,
    ExamRubric,
    GlobalPolicies,
    Question,
    QuestionGrade,
)


@pytest.fixture
def rubric() -> ExamRubric:
    return ExamRubric(
        exam_id="EXAM1",
        course="Algorithms",
        total_marks=15,
        policies=GlobalPolicies(),
        questions=[
            Question(
                question_id="Q1",
                question_text="...",
                max_marks=5,
                criteria=[Criterion(id="Q1_C1", description="x", marks=5)],
            ),
            Question(
                question_id="Q2",
                question_text="...",
                max_marks=5,
                criteria=[Criterion(id="Q2_C1", description="y", marks=5)],
            ),
            Question(
                question_id="Q3",
                question_text="...",
                max_marks=5,
                criteria=[Criterion(id="Q3_C1", description="z", marks=5)],
            ),
        ],
    )


def _student_answers(n_students: int = 3) -> list[dict]:
    return [
        {
            "student_id": f"STU{i:03d}",
            "answers": [
                {"question_id": "Q1", "text": "answer 1", "ocr_confidence": 0.9},
                {"question_id": "Q2", "text": "answer 2", "ocr_confidence": 0.85},
                {"question_id": "Q3", "text": "answer 3", "ocr_confidence": 0.95},
            ],
        }
        for i in range(1, n_students + 1)
    ]


def _make_grade(student_id: str, question_id: str, marks: float, max_marks: float = 5) -> QuestionGrade:
    return QuestionGrade(
        student_id=student_id,
        question_id=question_id,
        criterion_results=[],
        deduction_results=[],
        total_marks=marks,
        max_marks=max_marks,
        summary="ok",
        flags=[],
        verified=False,
    )


@pytest.mark.asyncio
async def test_three_students_three_questions_all_succeed(rubric):
    answers = _student_answers(3)

    async def fake_grade_question(student_id, question, *args, **kwargs):
        return _make_grade(student_id, question.question_id, 4.0)

    with patch(
        "gradeops.rubric_engine.batch.grade_question",
        side_effect=fake_grade_question,
    ) as mock:
        results = await grade_exam(rubric, answers, max_concurrency=5)

    assert mock.await_count == 9
    assert len(results) == 3
    for r in results:
        assert r.exam_id == "EXAM1"
        assert len(r.question_grades) == 3
        assert r.total_score == 12.0
        assert r.max_possible == 15
    # Sorted by student_id, then question_id within each student
    assert [r.student_id for r in results] == ["STU001", "STU002", "STU003"]
    for r in results:
        assert [g.question_id for g in r.question_grades] == ["Q1", "Q2", "Q3"]


@pytest.mark.asyncio
async def test_one_task_throws_other_eight_succeed(rubric):
    answers = _student_answers(3)
    call_count = {"n": 0}

    async def fake_grade_question(student_id, question, *args, **kwargs):
        call_count["n"] += 1
        if student_id == "STU002" and question.question_id == "Q2":
            raise RuntimeError("simulated failure")
        return _make_grade(student_id, question.question_id, 3.0)

    with patch(
        "gradeops.rubric_engine.batch.grade_question",
        side_effect=fake_grade_question,
    ):
        results = await grade_exam(rubric, answers, max_concurrency=5)

    assert call_count["n"] == 9
    # All 3 students should still appear, but STU002 only has 2 grades.
    by_id = {r.student_id: r for r in results}
    assert len(by_id) == 3
    assert len(by_id["STU001"].question_grades) == 3
    assert len(by_id["STU002"].question_grades) == 2
    assert len(by_id["STU003"].question_grades) == 3
    assert by_id["STU002"].total_score == 6.0  # 2 surviving questions * 3.0


@pytest.mark.asyncio
async def test_progress_callback_fires_correct_count(rubric):
    answers = _student_answers(2)
    progress_calls: list[tuple[int, int]] = []

    def on_progress(done, total):
        progress_calls.append((done, total))

    async def fake_grade_question(student_id, question, *args, **kwargs):
        return _make_grade(student_id, question.question_id, 5.0)

    with patch(
        "gradeops.rubric_engine.batch.grade_question",
        side_effect=fake_grade_question,
    ):
        await grade_exam(rubric, answers, max_concurrency=3, on_progress=on_progress)

    # 2 students x 3 questions = 6 tasks
    assert len(progress_calls) == 6
    # Final call must show full completion.
    assert progress_calls[-1] == (6, 6)
    # Each call must report the same total.
    assert all(total == 6 for _, total in progress_calls)
    # 'done' must monotonically increase.
    dones = [d for d, _ in progress_calls]
    assert dones == sorted(dones)
    assert dones[0] >= 1


@pytest.mark.asyncio
async def test_flags_are_aggregated_per_student(rubric):
    answers = _student_answers(1)

    async def fake_grade_question(student_id, question, *args, **kwargs):
        flags = ["LOW_OCR_CONFIDENCE"] if question.question_id == "Q2" else []
        if question.question_id == "Q3":
            flags = ["NEEDS_REVIEW"]
        return QuestionGrade(
            student_id=student_id,
            question_id=question.question_id,
            criterion_results=[],
            deduction_results=[],
            total_marks=2.0,
            max_marks=5.0,
            summary="ok",
            flags=flags,
            verified=False,
        )

    with patch(
        "gradeops.rubric_engine.batch.grade_question",
        side_effect=fake_grade_question,
    ):
        results = await grade_exam(rubric, answers)

    assert len(results) == 1
    assert set(results[0].flags) == {"LOW_OCR_CONFIDENCE", "NEEDS_REVIEW"}


@pytest.mark.asyncio
async def test_unknown_question_id_is_skipped(rubric):
    answers = [
        {
            "student_id": "STU001",
            "answers": [
                {"question_id": "Q1", "text": "answer", "ocr_confidence": 0.9},
                {"question_id": "Q999", "text": "bogus", "ocr_confidence": 0.9},
            ],
        }
    ]

    async def fake_grade_question(student_id, question, *args, **kwargs):
        return _make_grade(student_id, question.question_id, 4.0)

    with patch(
        "gradeops.rubric_engine.batch.grade_question",
        side_effect=fake_grade_question,
    ) as mock:
        results = await grade_exam(rubric, answers)

    assert mock.await_count == 1  # only Q1 was graded
    assert len(results) == 1
    assert len(results[0].question_grades) == 1
