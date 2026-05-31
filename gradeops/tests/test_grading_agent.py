"""Tests for the LangGraph grading agent — mocks all LLM calls."""
from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI

from gradeops.rubric_engine.grading_agent import grade_question
from gradeops.rubric_engine.schema import (
    Criterion,
    Deduction,
    GlobalPolicies,
    Question,
)


@contextlib.contextmanager
def mock_llm_ainvoke(mock: AsyncMock):
    """Patch ChatGoogleGenerativeAI.ainvoke at the class level.

    Patching the bound method on the module-level pydantic instance breaks at
    teardown (pydantic forbids delattr of methods inherited from the class),
    so we replace the class attribute instead.
    """
    with patch.object(ChatGoogleGenerativeAI, "ainvoke", mock):
        yield mock


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def policies() -> GlobalPolicies:
    return GlobalPolicies()


@pytest.fixture
def question() -> Question:
    return Question(
        question_id="Q1",
        question_text="Explain BST insertion complexity.",
        max_marks=10,
        criteria=[
            Criterion(id="Q1_C1", description="States O(log n)", marks=2),
            Criterion(
                id="Q1_C2",
                description="Explains height is log n",
                marks=3,
                partial_credit="Half if height mentioned but not explained",
            ),
            Criterion(
                id="Q1_C3",
                description="Walks through traversal",
                marks=3,
                partial_credit="1 per step",
            ),
            Criterion(
                id="Q1_C4",
                description="Mentions rebalancing",
                marks=2,
                partial_credit="1 if rotations mentioned",
            ),
        ],
        deductions=[
            Deduction(condition="Confuses BST with heap", penalty=-2),
        ],
    )


def _mock_llm_response(payload: dict | str):
    """Return an object with a `.content` attribute mimicking an AIMessage."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=content)


# ─────────────────────────────────────────────────────────────────────────────
# Happy paths
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_marks_path(question, policies):
    perfect = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Student wrote 'O(log n)' clearly."},
            {"criterion_id": "Q1_C2", "marks_awarded": 3.0, "justification": "Student explained height grows as log n due to balancing."},
            {"criterion_id": "Q1_C3", "marks_awarded": 3.0, "justification": "Student walked through compare, recurse, and insert steps."},
            {"criterion_id": "Q1_C4", "marks_awarded": 2.0, "justification": "Student noted rotations are amortized O(1)."},
        ],
        "deduction_results": [
            {"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0},
        ],
        "total_marks": 10.0,
        "summary": "Excellent answer covering complexity, height, traversal, and rebalancing.",
        "flags": [],
    }
    mock_ainvoke = AsyncMock(return_value=_mock_llm_response(perfect))

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU001",
            question=question,
            student_text="The complexity is O(log n) because tree height is log n...",
            ocr_confidence=0.9,
            policies=policies,
        )

    assert grade.total_marks == 10.0
    assert grade.max_marks == 10.0
    assert grade.verified is False
    assert grade.flags == [] or all(
        f not in {"UNREADABLE", "LLM_PARSE_ERROR", "NEEDS_REVIEW"} for f in grade.flags
    )
    assert mock_ainvoke.await_count == 1, "Happy path should only fire one LLM call"


@pytest.mark.asyncio
async def test_partial_marks_path(question, policies):
    partial = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Student stated 'O(log n)'."},
            {"criterion_id": "Q1_C2", "marks_awarded": 1.5, "justification": "Student mentioned height but not the balancing invariant."},
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Student described compare and insert but not recursion."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Student mentioned rotations without analyzing cost."},
        ],
        "deduction_results": [
            {"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0},
        ],
        "total_marks": 6.5,
        "summary": "Solid attempt with gaps in the height explanation and traversal walkthrough.",
        "flags": [],
    }
    mock_ainvoke = AsyncMock(return_value=_mock_llm_response(partial))

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU002",
            question=question,
            student_text="The answer is O(log n). Height is log n. We compare then insert.",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert grade.total_marks == 6.5
    # Validate the math was recomputed correctly: 2 + 1.5 + 2 + 1 = 6.5
    assert sum(cr.marks_awarded for cr in grade.criterion_results) == 6.5


# ─────────────────────────────────────────────────────────────────────────────
# Verification path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verification_triggered_by_contradiction(question, policies):
    """Justification says 'did not address' but full marks awarded — should trigger verify."""
    suspect = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Student wrote O(log n)."},
            {
                "criterion_id": "Q1_C2",
                "marks_awarded": 3.0,
                "justification": "Student did not address tree height at all.",
            },
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Student described traversal steps."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Student mentioned rotations."},
        ],
        "deduction_results": [{"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0}],
        "total_marks": 8.0,
        "summary": "Mostly thorough answer.",
        "flags": [],
    }
    verification = {
        "issues_found": [
            {
                "criterion_id": "Q1_C2",
                "issue": "Justification contradicts the marks awarded",
                "corrected_marks": 0.0,
            }
        ],
        "corrected_total": 5.0,
        "corrected_summary": "Reviewer corrected Q1_C2: student did not actually address tree height.",
        "verdict": "CORRECTED",
    }

    mock_ainvoke = AsyncMock(
        side_effect=[_mock_llm_response(suspect), _mock_llm_response(verification)]
    )

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU003",
            question=question,
            student_text="The complexity is O(log n). We compare and recurse and insert.",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 2, "Verification should have fired a second LLM call"
    assert grade.verified is True
    q1_c2 = next(cr for cr in grade.criterion_results if cr.criterion_id == "Q1_C2")
    assert q1_c2.marks_awarded == 0.0
    assert "VERIFIED_CORRECTED" in grade.flags
    # Total recomputed from corrected parts: 2 + 0 + 2 + 1 = 5
    assert grade.total_marks == 5.0


@pytest.mark.asyncio
async def test_verification_triggered_by_math_mismatch(question, policies):
    """LLM reports a total that doesn't match the sum of its own criterion marks."""
    suspect = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Stated O(log n)."},
            {"criterion_id": "Q1_C2", "marks_awarded": 2.0, "justification": "Explained height partially."},
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Described some steps."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Mentioned rotations."},
        ],
        "deduction_results": [{"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0}],
        "total_marks": 9.0,  # but real sum is 7
        "summary": "Solid answer.",
        "flags": [],
    }
    verification = {
        "issues_found": [],
        "corrected_total": 7.0,
        "corrected_summary": "Arithmetic corrected; criterion marks were fine.",
        "verdict": "CORRECTED",
    }

    mock_ainvoke = AsyncMock(
        side_effect=[_mock_llm_response(suspect), _mock_llm_response(verification)]
    )

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU004",
            question=question,
            student_text="O(log n). Compare, recurse, insert. Rotations rebalance.",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 2
    assert grade.verified is True
    assert grade.total_marks == 7.0


@pytest.mark.asyncio
async def test_verification_not_triggered_on_clean_grade(question, policies):
    """A clean grade with consistent math and no partial-credit edges should not verify."""
    clean = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 1.0, "justification": "Student stated complexity but imprecisely."},
            {"criterion_id": "Q1_C2", "marks_awarded": 1.5, "justification": "Mentioned height; matches partial credit rule."},
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Two of three steps described."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Mentioned rotations; matches partial credit rule."},
        ],
        "deduction_results": [{"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0}],
        "total_marks": 5.5,
        "summary": "Reasonable partial answer.",
        "flags": [],
    }
    mock_ainvoke = AsyncMock(return_value=_mock_llm_response(clean))

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU005",
            question=question,
            student_text="some legible answer",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 1, "No verification expected on clean grade"
    assert grade.verified is False
    assert grade.total_marks == 5.5


# ─────────────────────────────────────────────────────────────────────────────
# Failure paths
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_failure_retries_then_flags(question, policies):
    """First and second LLM calls return garbage — should flag LLM_PARSE_ERROR and 0 marks."""
    bad = _mock_llm_response("this is not JSON, just prose")
    mock_ainvoke = AsyncMock(side_effect=[bad, bad])

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU006",
            question=question,
            student_text="some legible answer",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 2, "Retry should happen exactly once"
    assert grade.total_marks == 0.0
    assert "LLM_PARSE_ERROR" in grade.flags
    assert grade.verified is False


@pytest.mark.asyncio
async def test_parse_failure_then_success_keeps_marks(question, policies):
    """First call fails, second succeeds — should grade normally."""
    good = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Stated O(log n)."},
            {"criterion_id": "Q1_C2", "marks_awarded": 1.5, "justification": "Mentioned height only."},
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Two of three steps."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Mentioned rotations."},
        ],
        "deduction_results": [{"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0}],
        "total_marks": 6.5,
        "summary": "Partial answer.",
        "flags": [],
    }
    mock_ainvoke = AsyncMock(
        side_effect=[_mock_llm_response("not json"), _mock_llm_response(good)]
    )

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU007",
            question=question,
            student_text="legible answer",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 2
    assert grade.total_marks == 6.5
    assert "LLM_PARSE_ERROR" not in grade.flags


@pytest.mark.asyncio
async def test_low_ocr_skips_llm(question, policies):
    mock_ainvoke = AsyncMock()

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU008",
            question=question,
            student_text="garbled text",
            ocr_confidence=0.3,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 0, "Low OCR should skip the LLM entirely"
    assert grade.total_marks == 0.0
    assert "UNREADABLE" in grade.flags
    assert "LOW_OCR_CONFIDENCE" in grade.flags


@pytest.mark.asyncio
async def test_empty_text_skips_llm(question, policies):
    mock_ainvoke = AsyncMock()
    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU009",
            question=question,
            student_text="   ",
            ocr_confidence=0.9,
            policies=policies,
        )
    assert mock_ainvoke.await_count == 0
    assert "UNREADABLE" in grade.flags
    assert grade.total_marks == 0.0


@pytest.mark.asyncio
async def test_verify_approved_path(question, policies):
    """When verification fires but the reviewer approves, the original marks survive."""
    suspect = {
        "criterion_results": [
            {"criterion_id": "Q1_C1", "marks_awarded": 2.0, "justification": "Stated O(log n)."},
            {"criterion_id": "Q1_C2", "marks_awarded": 1.5, "justification": "Mentioned height; matches partial credit rule."},
            {"criterion_id": "Q1_C3", "marks_awarded": 2.0, "justification": "Described compare and insert."},
            {"criterion_id": "Q1_C4", "marks_awarded": 1.0, "justification": "Mentioned rotations."},
        ],
        "deduction_results": [{"condition": "Confuses BST with heap", "applied": False, "penalty": 0.0}],
        # Real sum is 6.5 — reported total intentionally wrong to trigger math_mismatch.
        "total_marks": 8.0,
        "summary": "Solid partial answer.",
        "flags": [],
    }
    verification = {
        "issues_found": [],
        "corrected_total": 6.5,
        "corrected_summary": "Arithmetic fine after recompute; criterion marks confirmed.",
        "verdict": "APPROVED",
    }
    mock_ainvoke = AsyncMock(
        side_effect=[_mock_llm_response(suspect), _mock_llm_response(verification)]
    )

    with mock_llm_ainvoke(mock_ainvoke):
        grade = await grade_question(
            student_id="STU010",
            question=question,
            student_text="Comprehensive answer touching every criterion.",
            ocr_confidence=0.85,
            policies=policies,
        )

    assert mock_ainvoke.await_count == 2
    assert grade.verified is True
    # Reviewer APPROVED — we keep the original per-criterion marks (sum = 6.5).
    assert grade.total_marks == 6.5
    assert "VERIFIED_APPROVED" in grade.flags
