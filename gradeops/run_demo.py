"""End-to-end runnable demo of the GradeOps Rubric Engine.

Loads the sample rubric, runs three fake student submissions through the
LangGraph grading pipeline against Google Gemini, and prints the results.

Usage:
    python -m gradeops.run_demo

The Gemini API key is read from .env (GEMINI_API_KEY). Override the model
by setting GEMINI_MODEL (default: gemini-2.5-flash-lite).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Load .env BEFORE importing anything that constructs the LLM client.
from gradeops.rubric_engine.config import load_env

load_env()

from gradeops.rubric_engine import (  # noqa: E402  (env must load first)
    grade_exam,
    load_rubric,
    validate_rubric,
)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_RUBRIC = REPO_ROOT / "samples" / "sample_rubric.json"


# ─────────────────────────────────────────────────────────────────────────────
# Sample student submissions — varied quality so the pipeline gets exercised.
# ─────────────────────────────────────────────────────────────────────────────


STUDENT_ANSWERS: list[dict[str, Any]] = [
    {
        "student_id": "STU001",  # Strong student
        "answers": [
            {
                "question_id": "Q1",
                "ocr_confidence": 0.92,
                "text": (
                    "Inserting into a balanced BST takes O(log n) time. "
                    "The tree height is log(n) because the balancing invariant "
                    "(such as AVL or Red-Black) keeps the height bounded. "
                    "To insert, we compare the new key with the current node, "
                    "recurse into the left subtree if smaller or right subtree "
                    "if larger, until we reach a leaf where we attach the new node. "
                    "After insertion, rebalancing via rotations takes O(1) work "
                    "per rotation and is amortized O(1) overall."
                ),
            },
            {
                "question_id": "Q2",
                "ocr_confidence": 0.88,
                "text": (
                    "def has_cycle(head):\n"
                    "    if head is None or head.next is None:\n"
                    "        return False\n"
                    "    slow, fast = head, head\n"
                    "    while fast is not None and fast.next is not None:\n"
                    "        slow = slow.next\n"
                    "        fast = fast.next.next\n"
                    "        if slow is fast:\n"
                    "            return True\n"
                    "    return False\n"
                    "\n"
                    "Uses Floyd's tortoise and hare. Time O(n), space O(1). "
                    "Handles empty list, single node, and the no-cycle case via "
                    "the fast pointer reaching None."
                ),
            },
            {
                "question_id": "Q3",
                "ocr_confidence": 0.97,
                "text": "BFS visits every vertex once (O(V)) and every edge once (O(E)), so total O(V + E).",
            },
        ],
    },
    {
        "student_id": "STU002",  # Partial-credit student
        "answers": [
            {
                "question_id": "Q1",
                "ocr_confidence": 0.83,
                "text": (
                    "BST insertion is O(log n) because the height of the tree is "
                    "log n. We compare and then insert at the right spot."
                ),
            },
            {
                "question_id": "Q2",
                "ocr_confidence": 0.79,
                "text": (
                    "I would use a hash set. Walk through the list and add each "
                    "node to the set. If a node is already in the set, there's a "
                    "cycle. Time O(n), space O(n)."
                ),
            },
            {
                "question_id": "Q3",
                "ocr_confidence": 0.94,
                "text": "BFS is O(V).",
            },
        ],
    },
    {
        "student_id": "STU003",  # Unreadable / low OCR
        "answers": [
            {
                "question_id": "Q1",
                "ocr_confidence": 0.35,
                "text": "smudged ink — barely legible",
            },
            {
                "question_id": "Q2",
                "ocr_confidence": 0.90,
                "text": "",
            },
            {
                "question_id": "Q3",
                "ocr_confidence": 0.91,
                "text": "O(V + E)",
            },
        ],
    },
]


def _print_header(title: str) -> None:
    line = "─" * max(60, len(title))
    print(f"\n{line}\n{title}\n{line}")


def _on_progress(done: int, total: int) -> None:
    print(f"  [{done}/{total}] graded")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", default=str(DEFAULT_RUBRIC), help="Path to rubric JSON")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Max parallel Gemini calls (default: 2 — keep low on the free tier)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON of the final grades and exit",
    )
    args = parser.parse_args()

    rubric = load_rubric(args.rubric)
    warnings = validate_rubric(rubric)

    _print_header(f"Rubric loaded: {rubric.exam_id} — {rubric.course}")
    print(f"  Total marks: {rubric.total_marks}")
    print(f"  Questions:   {len(rubric.questions)}")
    print(f"  Warnings:    {warnings or 'none'}")

    _print_header("Grading 3 students × 3 questions = 9 tasks against Gemini")
    results = await grade_exam(
        rubric,
        STUDENT_ANSWERS,
        max_concurrency=args.concurrency,
        on_progress=_on_progress,
    )

    if args.json:
        payload = [r.model_dump() for r in results]
        print(json.dumps(payload, indent=2))
        return 0

    _print_header("Results")
    for student in results:
        flags_str = ", ".join(student.flags) if student.flags else "—"
        print(
            f"\n  {student.student_id}: "
            f"{student.total_score:.1f} / {student.max_possible:.1f}   "
            f"flags: [{flags_str}]"
        )
        for g in student.question_grades:
            verified = "✓verified" if g.verified else " "
            print(
                f"     {g.question_id}: {g.total_marks:.1f}/{g.max_marks:.1f}  {verified}  "
                f"flags={g.flags or '—'}"
            )
            print(f"        {g.summary}")
            for cr in g.criterion_results:
                print(f"        • {cr.criterion_id}: {cr.marks_awarded:.1f}  — {cr.justification}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
