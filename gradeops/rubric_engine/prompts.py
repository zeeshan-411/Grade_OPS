"""Prompt templates for the grading and verification LLM calls."""
from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from .schema import GlobalPolicies, Question


# ─────────────────────────────────────────────────────────────────────────────
# Grade prompt — always runs
# ─────────────────────────────────────────────────────────────────────────────

GRADE_SYSTEM = """You are an expert exam grader. You evaluate a student's handwritten answer against a rubric.
The answer was extracted via OCR from handwriting — minor transcription errors (O vs 0, l vs 1, missing spaces) should not be penalized.
Focus on the logical content and reasoning."""

GRADE_HUMAN = """QUESTION:
{question_text}

MAX MARKS: {max_marks}

RUBRIC CRITERIA:
{criteria_block}

{deductions_block}

{alternatives_block}

{grader_notes_block}

{policy_block}

STUDENT'S ANSWER (OCR confidence: {ocr_confidence}):
---
{student_text}
---

INSTRUCTIONS:
1. Evaluate each criterion independently. For each, decide marks_awarded (0 to criterion max) and write a 1-sentence justification that cites the student's answer.
2. Check each deduction condition. Apply the penalty only if clearly triggered.
3. Compute total = sum of criterion marks + sum of applied penalties. Clamp to [0, {max_marks}].
4. Write a 2-3 sentence summary of the overall grade for a TA reviewer.
5. Set flags: include "UNREADABLE" if answer is empty/garbled, "LOW_OCR_CONFIDENCE" if OCR confidence < 0.6.

Respond with ONLY valid JSON matching this exact structure (no markdown, no backticks):
{{
  "criterion_results": [
    {{"criterion_id": "...", "marks_awarded": 0.0, "justification": "..."}}
  ],
  "deduction_results": [
    {{"condition": "...", "applied": false, "penalty": 0.0}}
  ],
  "total_marks": 0.0,
  "summary": "...",
  "flags": []
}}"""

grade_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", GRADE_SYSTEM),
        ("human", GRADE_HUMAN),
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# Verify prompt — conditional second call
# ─────────────────────────────────────────────────────────────────────────────

VERIFY_SYSTEM = """You are a senior exam grading reviewer. You are checking another grader's work for errors.
You will see the original question, rubric, student answer, and the proposed grade. Your job is to find mistakes."""

VERIFY_HUMAN = """QUESTION:
{question_text}

MAX MARKS: {max_marks}

RUBRIC CRITERIA:
{criteria_block}

STUDENT'S ANSWER:
---
{student_text}
---

PROPOSED GRADE:
{proposed_grade_json}

REVIEW CHECKLIST:
1. Does each criterion's marks_awarded match its justification? (e.g., justification says "student did not mention X" but marks are full)
2. Are any deductions applied incorrectly? (penalizing something the student didn't do)
3. Are any deductions missed? (student made the error but no penalty applied)
4. Is the total_marks arithmetic correct?
5. Is the summary consistent with the individual criterion results?

Respond with ONLY valid JSON:
{{
  "issues_found": [
    {{"criterion_id": "...", "issue": "...", "corrected_marks": 0.0}}
  ],
  "corrected_total": 0.0,
  "corrected_summary": "...",
  "verdict": "APPROVED" or "CORRECTED"
}}"""

verify_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", VERIFY_SYSTEM),
        ("human", VERIFY_HUMAN),
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# Template variable builders
# ─────────────────────────────────────────────────────────────────────────────


def _format_criteria_block(question: Question) -> str:
    lines = []
    for c in question.criteria:
        line = f"- [{c.id}] (max {c.marks} marks) {c.description}"
        if c.partial_credit:
            line += f"\n    PARTIAL CREDIT RULE: {c.partial_credit}"
        lines.append(line)
    return "\n".join(lines)


def _format_deductions_block(question: Question) -> str:
    if not question.deductions:
        return ""
    lines = ["DEDUCTIONS (apply only if clearly triggered):"]
    for d in question.deductions:
        lines.append(f"- {d.condition} (penalty: {d.penalty})")
    return "\n".join(lines)


def _format_alternatives_block(question: Question) -> str:
    if not question.alternatives:
        return ""
    lines = ["ALTERNATIVE ACCEPTABLE ANSWERS:"]
    for a in question.alternatives:
        lines.append(f"- {a.description} — {a.instruction}")
    return "\n".join(lines)


def _format_grader_notes_block(question: Question) -> str:
    if not question.grader_notes:
        return ""
    return f"GRADER NOTES:\n{question.grader_notes}"


def _format_policy_block(policies: GlobalPolicies, ocr_confidence: float) -> str:
    parts: list[str] = []
    if not policies.partial_credit:
        parts.append("POLICY: Partial credit is DISABLED — award full marks or zero.")
    if ocr_confidence < policies.ocr_confidence_floor:
        parts.append(f"POLICY (OCR low): {policies.abstain_policy}")
    return "\n".join(parts)


def format_grading_inputs(
    question: Question,
    student_text: str,
    ocr_confidence: float,
    policies: GlobalPolicies,
) -> dict:
    """Build the dict of template variables for grade_prompt.invoke()."""
    return {
        "question_text": question.question_text,
        "max_marks": question.max_marks,
        "criteria_block": _format_criteria_block(question),
        "deductions_block": _format_deductions_block(question),
        "alternatives_block": _format_alternatives_block(question),
        "grader_notes_block": _format_grader_notes_block(question),
        "policy_block": _format_policy_block(policies, ocr_confidence),
        "ocr_confidence": f"{ocr_confidence:.2f}",
        "student_text": student_text if student_text.strip() else "[empty]",
    }


def format_verification_inputs(
    question: Question,
    student_text: str,
    proposed_grade_json: str,
) -> dict:
    """Build the dict of template variables for verify_prompt.invoke()."""
    return {
        "question_text": question.question_text,
        "max_marks": question.max_marks,
        "criteria_block": _format_criteria_block(question),
        "student_text": student_text if student_text.strip() else "[empty]",
        "proposed_grade_json": proposed_grade_json,
    }
