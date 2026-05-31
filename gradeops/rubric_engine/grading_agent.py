"""LangGraph grading agent with conditional verification.

Design constraint: maximum 2 LLM calls per (student, question) pair.
- check_ocr, validate_and_route, apply_corrections, finalize, flag_unreadable
  are pure logic (no LLM).
- grade is LLM call #1 (always).
- verify is LLM call #2 (conditional).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from .config import load_env
from .prompts import (
    format_grading_inputs,
    format_verification_inputs,
    grade_prompt,
    verify_prompt,
)
from .schema import (
    CriterionResult,
    DeductionResult,
    GlobalPolicies,
    Question,
    QuestionGrade,
)
from .utils import detect_suspicion, extract_json, is_text_unreadable, recompute_total

log = logging.getLogger(__name__)

MAX_GRADE_ATTEMPTS = 2

# Eagerly load .env so the API key is in the environment before LangChain reads it.
load_env()


DEFAULT_MODEL = "gemini-2.5-flash-lite"


def _build_llm() -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    # Read the model name at construction time so callers can change it via the env.
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        max_output_tokens=2048,
        temperature=0.0,
    )


llm = _build_llm()


def set_model(model: str) -> None:
    """Swap the global LLM to a different Gemini model at runtime.

    Used by the Streamlit app to honor the model setting without forcing a process
    restart. Keeps the same singleton `llm` reference that the graph nodes capture.
    """
    global llm
    os.environ["GEMINI_MODEL"] = model
    llm = _build_llm()


class GradingState(TypedDict, total=False):
    # Inputs
    student_id: str
    question: Question
    student_text: str
    ocr_confidence: float
    policies: GlobalPolicies

    # After grade call
    raw_grade_response: dict | None
    grade: QuestionGrade | None

    # After verification (if triggered)
    needs_verification: bool
    suspicion_reasons: list[str]
    verification_response: dict | None
    verified: bool

    # Control
    error: str | None
    attempt: int
    extra_flags: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Node implementations
# ─────────────────────────────────────────────────────────────────────────────


def check_ocr(state: GradingState) -> GradingState:
    """Pure logic — routing handled by the conditional edge."""
    state.setdefault("extra_flags", [])
    return state


def flag_unreadable(state: GradingState) -> GradingState:
    """Build a zero-marks QuestionGrade with the UNREADABLE flag."""
    question: Question = state["question"]
    flags = ["UNREADABLE"]
    if state["ocr_confidence"] < state["policies"].ocr_confidence_floor:
        flags.append("LOW_OCR_CONFIDENCE")

    state["grade"] = QuestionGrade(
        student_id=state["student_id"],
        question_id=question.question_id,
        criterion_results=[
            CriterionResult(
                criterion_id=c.id,
                marks_awarded=0.0,
                justification="Answer was unreadable; no marks awarded.",
            )
            for c in question.criteria
        ],
        deduction_results=[
            DeductionResult(condition=d.condition, applied=False, penalty=0.0)
            for d in question.deductions
        ],
        total_marks=0.0,
        max_marks=question.max_marks,
        summary="The student's answer could not be read and was assigned zero marks per the abstain policy.",
        flags=flags,
        verified=False,
    )
    return state


async def grade(state: GradingState) -> GradingState:
    """LLM call #1 — evaluate all criteria and deductions in a single shot."""
    state["attempt"] = state.get("attempt", 0) + 1

    if is_text_unreadable(state["student_text"]):
        # Short-circuit: skip the LLM and fall through to flag_unreadable behavior
        # at finalize time. We still set an empty result so the validator passes.
        state["raw_grade_response"] = {
            "criterion_results": [
                {
                    "criterion_id": c.id,
                    "marks_awarded": 0.0,
                    "justification": "Answer was empty.",
                }
                for c in state["question"].criteria
            ],
            "deduction_results": [
                {"condition": d.condition, "applied": False, "penalty": 0.0}
                for d in state["question"].deductions
            ],
            "total_marks": 0.0,
            "summary": "The student's submission was empty.",
            "flags": ["UNREADABLE"],
        }
        state["error"] = None
        return state

    inputs = format_grading_inputs(
        question=state["question"],
        student_text=state["student_text"],
        ocr_confidence=state["ocr_confidence"],
        policies=state["policies"],
    )
    messages = grade_prompt.format_messages(**inputs)

    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = extract_json(content)
        state["raw_grade_response"] = parsed
        state["error"] = None
    except ValueError as exc:
        log.warning("grade: JSON parse error on attempt %d: %s", state["attempt"], exc)
        state["error"] = "parse_error"
        state["raw_grade_response"] = None
    except Exception as exc:  # noqa: BLE001 — surface any LLM failure as an error flag
        log.exception("grade: unexpected error on attempt %d", state["attempt"])
        state["error"] = f"llm_error:{type(exc).__name__}"
        state["raw_grade_response"] = None

    return state


def validate_and_route(state: GradingState) -> GradingState:
    """Pure logic — decide whether the grade is suspicious."""
    parsed = state.get("raw_grade_response")
    if parsed is None:
        state["needs_verification"] = False
        state["suspicion_reasons"] = []
        return state

    is_suspicious, reasons = detect_suspicion(parsed, state["question"])
    state["needs_verification"] = is_suspicious
    state["suspicion_reasons"] = reasons
    return state


async def verify(state: GradingState) -> GradingState:
    """LLM call #2 — only runs when validate_and_route flagged the grade."""
    inputs = format_verification_inputs(
        question=state["question"],
        student_text=state["student_text"],
        proposed_grade_json=json.dumps(state["raw_grade_response"], indent=2),
    )
    messages = verify_prompt.format_messages(**inputs)

    try:
        response = await llm.ainvoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        state["verification_response"] = extract_json(content)
        state["verified"] = True
    except ValueError as exc:
        log.warning("verify: JSON parse error: %s", exc)
        state["verification_response"] = None
        state["verified"] = False
        state.setdefault("extra_flags", []).append("VERIFY_PARSE_ERROR")
    except Exception as exc:  # noqa: BLE001
        log.exception("verify: unexpected error")
        state["verification_response"] = None
        state["verified"] = False
        state.setdefault("extra_flags", []).append(f"VERIFY_ERROR_{type(exc).__name__}")

    return state


def apply_corrections(state: GradingState) -> GradingState:
    """Pure logic — fold verification corrections into raw_grade_response."""
    vr = state.get("verification_response")
    parsed = state.get("raw_grade_response")
    extra_flags = state.setdefault("extra_flags", [])

    if not vr or not parsed:
        return state

    verdict = vr.get("verdict", "").upper()

    if verdict == "APPROVED":
        extra_flags.append("VERIFIED_APPROVED")
        return state

    if verdict == "CORRECTED":
        issues = {issue["criterion_id"]: issue for issue in vr.get("issues_found", [])}
        for cr in parsed.get("criterion_results", []):
            cid = cr.get("criterion_id")
            if cid in issues and "corrected_marks" in issues[cid]:
                cr["marks_awarded"] = float(issues[cid]["corrected_marks"])
                cr["justification"] = (
                    cr.get("justification", "")
                    + f" [Reviewer correction: {issues[cid].get('issue', '')}]"
                )

        corrected_total = vr.get("corrected_total")
        if corrected_total is not None:
            parsed["total_marks"] = float(corrected_total)

        corrected_summary = vr.get("corrected_summary")
        if corrected_summary:
            parsed["summary"] = corrected_summary

        extra_flags.append("VERIFIED_CORRECTED")
        extra_flags.append("MATH_CORRECTED")
        return state

    # Unknown verdict — flag but keep the original grade.
    extra_flags.append(f"VERIFY_UNKNOWN_VERDICT_{verdict or 'EMPTY'}")
    return state


def finalize(state: GradingState) -> GradingState:
    """Build the final QuestionGrade. Always recompute total from parts."""
    question: Question = state["question"]
    parsed = state.get("raw_grade_response")
    extra_flags = list(state.get("extra_flags", []))

    if parsed is None:
        # Distinguish API failures (e.g. 429 quota exhaustion) from JSON parse failures.
        err = state.get("error") or ""
        if err.startswith("llm_error"):
            error_flag = "LLM_API_ERROR"
            justification = "LLM call failed (see logs)."
            summary = "Grading failed because the LLM API call did not succeed."
        else:
            error_flag = "LLM_PARSE_ERROR"
            justification = "LLM response could not be parsed."
            summary = "Grading failed because the LLM response could not be parsed."

        state["grade"] = QuestionGrade(
            student_id=state["student_id"],
            question_id=question.question_id,
            criterion_results=[
                CriterionResult(
                    criterion_id=c.id,
                    marks_awarded=0.0,
                    justification=justification,
                )
                for c in question.criteria
            ],
            deduction_results=[
                DeductionResult(condition=d.condition, applied=False, penalty=0.0)
                for d in question.deductions
            ],
            total_marks=0.0,
            max_marks=question.max_marks,
            summary=summary,
            flags=list({error_flag, "NEEDS_REVIEW", *extra_flags}),
            verified=False,
        )
        return state

    criterion_results: list[CriterionResult] = []
    declared_ids = {c.id for c in question.criteria}
    for cr in parsed.get("criterion_results", []):
        cid = cr.get("criterion_id")
        if cid not in declared_ids:
            continue
        criterion_results.append(
            CriterionResult(
                criterion_id=cid,
                marks_awarded=float(cr.get("marks_awarded", 0.0)),
                justification=str(cr.get("justification", "")),
            )
        )

    # Ensure every rubric criterion is present, even if the LLM skipped one.
    present_ids = {cr.criterion_id for cr in criterion_results}
    for c in question.criteria:
        if c.id not in present_ids:
            criterion_results.append(
                CriterionResult(
                    criterion_id=c.id,
                    marks_awarded=0.0,
                    justification="Criterion missing from LLM response; defaulted to 0.",
                )
            )
            extra_flags.append("NEEDS_REVIEW")

    deduction_results: list[DeductionResult] = []
    for d in question.deductions:
        match = next(
            (
                dr
                for dr in parsed.get("deduction_results", [])
                if dr.get("condition") == d.condition
            ),
            None,
        )
        applied = bool(match.get("applied")) if match else False
        deduction_results.append(
            DeductionResult(
                condition=d.condition,
                applied=applied,
                penalty=d.penalty if applied else 0.0,
            )
        )

    total = recompute_total(
        [cr.marks_awarded for cr in criterion_results],
        [dr.penalty for dr in deduction_results if dr.applied],
        question.max_marks,
    )

    flags = list(parsed.get("flags", []))
    if state["ocr_confidence"] < state["policies"].ocr_confidence_floor:
        if "LOW_OCR_CONFIDENCE" not in flags:
            flags.append("LOW_OCR_CONFIDENCE")
    flags.extend(extra_flags)
    if state.get("error"):
        flags.append("NEEDS_REVIEW")
    # De-duplicate, preserve order.
    seen: set[str] = set()
    deduped_flags = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            deduped_flags.append(f)

    state["grade"] = QuestionGrade(
        student_id=state["student_id"],
        question_id=question.question_id,
        criterion_results=criterion_results,
        deduction_results=deduction_results,
        total_marks=total,
        max_marks=question.max_marks,
        summary=str(parsed.get("summary", "")),
        flags=deduped_flags,
        verified=bool(state.get("verified", False)),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Graph construction
# ─────────────────────────────────────────────────────────────────────────────


def _after_ocr(state: GradingState) -> str:
    if state["ocr_confidence"] < state["policies"].ocr_confidence_floor:
        return "flag_unreadable"
    if is_text_unreadable(state["student_text"]):
        return "flag_unreadable"
    return "grade"


def _after_grade(state: GradingState) -> str:
    if state.get("error") == "parse_error" and state.get("attempt", 0) < MAX_GRADE_ATTEMPTS:
        return "grade"
    if state.get("error") == "parse_error":
        return "finalize"
    if state.get("error", "").startswith("llm_error") if state.get("error") else False:
        return "finalize"
    return "validate_and_route"


def _after_validate(state: GradingState) -> str:
    return "verify" if state.get("needs_verification") else "finalize"


def build_grading_graph() -> Any:
    graph = StateGraph(GradingState)

    graph.add_node("check_ocr", check_ocr)
    graph.add_node("flag_unreadable", flag_unreadable)
    graph.add_node("grade", grade)
    graph.add_node("validate_and_route", validate_and_route)
    graph.add_node("verify", verify)
    graph.add_node("apply_corrections", apply_corrections)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("check_ocr")

    graph.add_conditional_edges(
        "check_ocr",
        _after_ocr,
        {"flag_unreadable": "flag_unreadable", "grade": "grade"},
    )

    graph.add_conditional_edges(
        "grade",
        _after_grade,
        {"grade": "grade", "finalize": "finalize", "validate_and_route": "validate_and_route"},
    )

    graph.add_conditional_edges(
        "validate_and_route",
        _after_validate,
        {"verify": "verify", "finalize": "finalize"},
    )

    graph.add_edge("flag_unreadable", END)
    graph.add_edge("verify", "apply_corrections")
    graph.add_edge("apply_corrections", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


grading_graph = build_grading_graph()


# ─────────────────────────────────────────────────────────────────────────────
# Public runner
# ─────────────────────────────────────────────────────────────────────────────


async def grade_question(
    student_id: str,
    question: Question,
    student_text: str,
    ocr_confidence: float,
    policies: GlobalPolicies,
) -> QuestionGrade:
    """Grade one student's answer to one question."""
    initial_state: GradingState = {
        "student_id": student_id,
        "question": question,
        "student_text": student_text,
        "ocr_confidence": ocr_confidence,
        "policies": policies,
        "raw_grade_response": None,
        "grade": None,
        "needs_verification": False,
        "suspicion_reasons": [],
        "verification_response": None,
        "verified": False,
        "error": None,
        "attempt": 0,
        "extra_flags": [],
    }

    final_state = await grading_graph.ainvoke(initial_state)
    return final_state["grade"]
