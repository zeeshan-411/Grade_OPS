"""Async batch orchestrator for grading entire exams."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable

from .grading_agent import grade_question
from .schema import ExamRubric, QuestionGrade, StudentExamGrade

log = logging.getLogger(__name__)


async def grade_exam(
    rubric: ExamRubric,
    student_answers: list[dict],
    max_concurrency: int = 10,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[StudentExamGrade]:
    """Grade every student in student_answers against the rubric.

    student_answers format:
        [{"student_id": "STU001",
          "answers": [{"question_id": "Q1", "text": "...", "ocr_confidence": 0.85}, ...]}]

    - Concurrency is bounded by max_concurrency via a semaphore.
    - on_progress(completed, total) fires after each task finishes (success or failure).
    - Tasks that raise are dropped from the output but logged; the rest still return.
    """
    sem = asyncio.Semaphore(max_concurrency)
    question_map = {q.question_id: q for q in rubric.questions}
    total_tasks = sum(len(s["answers"]) for s in student_answers)
    completed = 0
    lock = asyncio.Lock()

    async def run_one(sid: str, question, text: str, confidence: float) -> QuestionGrade:
        nonlocal completed
        async with sem:
            try:
                result = await grade_question(sid, question, text, confidence, rubric.policies)
                return result
            finally:
                async with lock:
                    completed += 1
                    if on_progress:
                        try:
                            on_progress(completed, total_tasks)
                        except Exception:  # noqa: BLE001
                            log.exception("on_progress callback raised; continuing")

    tasks = []
    for student in student_answers:
        sid = student["student_id"]
        for answer in student["answers"]:
            qid = answer["question_id"]
            if qid not in question_map:
                log.warning(
                    "Student %s submitted answer to unknown question %s — skipping",
                    sid,
                    qid,
                )
                continue
            tasks.append(
                run_one(
                    sid,
                    question_map[qid],
                    answer["text"],
                    float(answer["ocr_confidence"]),
                )
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    clean_results: list[QuestionGrade] = []
    for r in results:
        if isinstance(r, Exception):
            log.error("grade_question raised: %s", r)
            continue
        clean_results.append(r)

    grouped: dict[str, list[QuestionGrade]] = defaultdict(list)
    for grade in clean_results:
        grouped[grade.student_id].append(grade)

    output: list[StudentExamGrade] = []
    for student_id, grades in grouped.items():
        all_flags = sorted({f for g in grades for f in g.flags})
        output.append(
            StudentExamGrade(
                student_id=student_id,
                exam_id=rubric.exam_id,
                question_grades=sorted(grades, key=lambda g: g.question_id),
                total_score=sum(g.total_marks for g in grades),
                max_possible=rubric.total_marks,
                flags=all_flags,
            )
        )

    output.sort(key=lambda s: s.student_id)
    return output
