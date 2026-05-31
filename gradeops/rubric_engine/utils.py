"""Helper functions: JSON extraction, math checks, suspicion detection."""
from __future__ import annotations

import json
import math
import re

from .schema import Question


JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

# Phrases that contradict a positive marks award.
CONTRADICTION_PHRASES = (
    "did not address",
    "did not mention",
    "does not address",
    "does not mention",
    "did not answer",
    "does not answer",
    "no mention",
    "did not attempt",
    "did not provide",
    "does not provide",
    "did not explain",
    "does not explain",
    "fails to address",
    "fails to mention",
    "fails to explain",
    "is missing",
    "is absent",
    "omits",
    "omitted",
    "left blank",
    "no answer",
    "did not include",
    "does not include",
)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response.

    Strips markdown fences first, then attempts a direct json.loads, falling
    back to a regex scan. Raises ValueError if nothing parses.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Could not parse JSON from LLM response: {exc}") from exc

    raise ValueError("No JSON object found in LLM response")


def math_is_consistent(
    criterion_marks: list[float],
    applied_penalties: list[float],
    reported_total: float,
    max_marks: float,
    tolerance: float = 0.01,
) -> bool:
    """Check that reported_total matches the clamped sum of marks and penalties."""
    raw = sum(criterion_marks) + sum(applied_penalties)
    expected = max(0.0, min(max_marks, raw))
    return math.isclose(expected, reported_total, abs_tol=tolerance)


def has_contradictory_justification(justification: str, marks_awarded: float) -> bool:
    """True if the justification says the student did not do the thing but marks > 0."""
    if marks_awarded <= 0:
        return False
    lowered = justification.lower()
    return any(phrase in lowered for phrase in CONTRADICTION_PHRASES)


def is_suspiciously_uniform(criterion_results: list[dict], criteria_max: list[float]) -> bool:
    """True if every criterion got the same intermediate fraction of its max.

    Uniform 100% (genuine perfect answer) or uniform 0% (genuine empty answer) is not
    suspicious — both are consistent outcomes. The lazy-grading pattern is an LLM
    settling on the same non-trivial fraction for every criterion (e.g., every score is 60%).
    """
    if len(criterion_results) < 2:
        return False
    fractions = []
    for cr, max_marks in zip(criterion_results, criteria_max):
        if max_marks <= 0:
            continue
        fractions.append(round(cr["marks_awarded"] / max_marks, 3))
    if len(fractions) < 2:
        return False
    if len(set(fractions)) != 1:
        return False
    uniform_fraction = fractions[0]
    # Allow uniform 0% and 100% — they're consistent, not lazy.
    return 0.0 < uniform_fraction < 1.0


def detect_suspicion(parsed: dict, question: Question) -> tuple[bool, list[str]]:
    """Apply the four-rule suspicion check.

    Returns (is_suspicious, list_of_reasons).
    """
    reasons: list[str] = []

    criterion_results = parsed.get("criterion_results", [])
    deduction_results = parsed.get("deduction_results", [])
    reported_total = float(parsed.get("total_marks", 0.0))

    criterion_marks = [float(cr.get("marks_awarded", 0.0)) for cr in criterion_results]
    applied_penalties = [
        float(dr.get("penalty", 0.0)) for dr in deduction_results if dr.get("applied")
    ]

    # Rule 1: math mismatch
    if not math_is_consistent(
        criterion_marks, applied_penalties, reported_total, question.max_marks
    ):
        reasons.append("math_mismatch")

    # Rule 2: contradiction between justification and marks
    for cr in criterion_results:
        if has_contradictory_justification(
            cr.get("justification", ""), float(cr.get("marks_awarded", 0.0))
        ):
            reasons.append(f"contradiction:{cr.get('criterion_id')}")
            break

    # Rule 3: edge scores on partial-credit criteria — only suspicious when MIXED.
    # If every partial-credit criterion is at max (genuine perfect answer) or every one
    # is at 0 (genuine empty), that's consistent, not lazy. The lazy pattern is awarding
    # binary 0/max to some criteria while giving partial marks to others.
    criteria_by_id = {c.id: c for c in question.criteria}
    edge_hits: list[str] = []
    non_edge_hits: list[str] = []
    for cr in criterion_results:
        c = criteria_by_id.get(cr.get("criterion_id"))
        if c is None or not c.partial_credit:
            continue
        marks = float(cr.get("marks_awarded", 0.0))
        if math.isclose(marks, 0.0, abs_tol=0.01) or math.isclose(
            marks, c.marks, abs_tol=0.01
        ):
            edge_hits.append(c.id)
        else:
            non_edge_hits.append(c.id)
    if edge_hits and non_edge_hits:
        reasons.append(f"edge_scores_mixed:{','.join(edge_hits)}")

    # Rule 4: suspiciously uniform
    criteria_max = [
        criteria_by_id[cr["criterion_id"]].marks
        for cr in criterion_results
        if cr.get("criterion_id") in criteria_by_id
    ]
    if is_suspiciously_uniform(criterion_results, criteria_max):
        reasons.append("uniform_grading")

    return (len(reasons) > 0, reasons)


def recompute_total(
    criterion_marks: list[float],
    applied_penalties: list[float],
    max_marks: float,
) -> float:
    """Sum, clamp to [0, max_marks]."""
    raw = sum(criterion_marks) + sum(applied_penalties)
    return max(0.0, min(max_marks, raw))


def is_text_unreadable(text: str) -> bool:
    """Empty, whitespace, or known sentinels."""
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.lower() in {"[unreadable]", "[empty]", "[blank]"}
