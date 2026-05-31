# GradeOps — Module 2: Rubric Engine + LLM Grading Pipeline

## Context

You are building Module 2 of **GradeOps**, an AI-powered exam grading system for universities. This module receives extracted text from handwritten exam answers (produced by a separate OCR pipeline — Module 1) and grades them against structured JSON rubrics using an agentic LLM pipeline built with LangGraph.

The output is a structured grade object per student-question pair, with scores, justifications, and flags — consumed downstream by a TA review dashboard (Module 4).

---

## Design Philosophy: Minimal LLM Calls

- **Happy path: 1 LLM call** — A single call evaluates all criteria, applies deductions, and produces the complete grade.
- **Verification path: +1 call (conditional)** — A second call fires ONLY when the first response is suspicious (math errors, contradictory justifications, edge-case scores). This is where LangGraph earns its keep — the conditional routing.
- **Maximum: 2 calls per student-question pair.** Never more.

---

## Tech Stack

- **Python 3.11+**
- **LangChain** for LLM abstraction, prompt templates, and structured output parsing
- **LangGraph** for the grading agent state machine with conditional verification
- **Anthropic Claude claude-sonnet-4-20250514** via `langchain-anthropic`
- **Pydantic v2** for all data models
- **pytest + pytest-asyncio** for tests
- **asyncio** for batch concurrency

---

## Directory Structure

```
gradeops/
├── rubric_engine/
│   ├── __init__.py
│   ├── schema.py              # Pydantic models for rubric + grade output
│   ├── validator.py           # Rubric JSON loader, validator, normalizer
│   ├── prompts.py             # Prompt templates (grade + verify)
│   ├── grading_agent.py       # LangGraph agent with conditional verification
│   ├── batch.py               # Async batch runner
│   └── utils.py               # Helpers (math check, flag logic, etc.)
├── rubrics/
│   └── sample_rubric.json     # Working example
├── tests/
│   ├── test_validator.py
│   ├── test_grading_agent.py
│   └── test_batch.py
├── requirements.txt
└── README.md
```

---

## Step 1: Rubric Schema (`schema.py`)

Flat, plain-English rubric. No eval_method enums — the LLM interprets criteria descriptions directly.

### Rubric Input Models

```python
from pydantic import BaseModel
from typing import Literal

class Criterion(BaseModel):
    id: str                             # "Q1_C1"
    description: str                    # What to look for — plain English
    marks: float                        # Max marks for this criterion
    partial_credit: str | None = None   # e.g. "Award 1 if mentioned but not explained"

class Deduction(BaseModel):
    condition: str                      # When to apply
    penalty: float                      # Negative number

class AlternativeAnswer(BaseModel):
    description: str
    instruction: str                    # e.g. "Accept as equivalent" or "Cap Q2_C1 at 2 marks"

class Question(BaseModel):
    question_id: str
    question_text: str
    max_marks: float
    criteria: list[Criterion]
    deductions: list[Deduction] = []
    alternatives: list[AlternativeAnswer] = []
    grader_notes: str | None = None

class GlobalPolicies(BaseModel):
    partial_credit: bool = True
    ocr_confidence_floor: float = 0.6
    abstain_policy: str = "If the extracted text is unreadable or empty, assign 0 marks to all criteria and set flag UNREADABLE."

class ExamRubric(BaseModel):
    exam_id: str
    course: str
    total_marks: float
    policies: GlobalPolicies = GlobalPolicies()
    questions: list[Question]
```

### Grade Output Models

```python
class CriterionResult(BaseModel):
    criterion_id: str
    marks_awarded: float
    justification: str              # 1 sentence, must quote the student's answer

class DeductionResult(BaseModel):
    condition: str
    applied: bool
    penalty: float                  # 0 if not applied

class QuestionGrade(BaseModel):
    student_id: str
    question_id: str
    criterion_results: list[CriterionResult]
    deduction_results: list[DeductionResult]
    total_marks: float
    max_marks: float
    summary: str                    # 2-3 sentence justification for the TA
    flags: list[str]                # ["LOW_OCR_CONFIDENCE", "UNREADABLE", "NEEDS_REVIEW", "MATH_CORRECTED"]
    verified: bool                  # True if verification call was triggered and passed

class StudentExamGrade(BaseModel):
    student_id: str
    exam_id: str
    question_grades: list[QuestionGrade]
    total_score: float
    max_possible: float
    flags: list[str]
```

---

## Step 2: Rubric Validator (`validator.py`)

```python
def load_rubric(path: str) -> ExamRubric:
    """Load JSON, parse into ExamRubric. Raise clear errors on invalid input."""

def validate_rubric(rubric: ExamRubric) -> list[str]:
    """Return warnings:
    - Criteria marks don't sum to question max_marks
    - Question max_marks don't sum to exam total_marks
    - Criterion with marks > 2 has no partial_credit instruction
    - Duplicate criterion IDs
    """

def normalize_rubric(rubric: ExamRubric) -> ExamRubric:
    """Auto-fix: deduplicate criterion IDs, strip whitespace."""
```

---

## Step 3: Prompt Templates (`prompts.py`)

Two prompts. That's it.

### Prompt 1: Grade (always runs)

```python
from langchain_core.prompts import ChatPromptTemplate

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

grade_prompt = ChatPromptTemplate.from_messages([
    ("system", GRADE_SYSTEM),
    ("human", GRADE_HUMAN),
])
```

Build a helper function to format the template variables:

```python
def format_grading_inputs(question: Question, student_text: str, ocr_confidence: float, policies: GlobalPolicies) -> dict:
    """Build the dict of template variables for grade_prompt.invoke().
    
    - criteria_block: Formatted list of criteria with IDs, marks, descriptions, partial credit rules.
    - deductions_block: Formatted deductions or empty string if none.
    - alternatives_block: Formatted alternatives or empty string if none.
    - grader_notes_block: Grader notes or empty string.
    - policy_block: Partial credit disabled note + abstain policy if OCR is low.
    """
```

### Prompt 2: Verify (conditional — only runs when triggered)

```python
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

verify_prompt = ChatPromptTemplate.from_messages([
    ("system", VERIFY_SYSTEM),
    ("human", VERIFY_HUMAN),
])
```

---

## Step 4: LangGraph Grading Agent (`grading_agent.py`)

### Agent State

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END

class GradingState(TypedDict):
    # Inputs (set once at start)
    student_id: str
    question: Question              # The rubric question
    student_text: str
    ocr_confidence: float
    policies: GlobalPolicies

    # After grade call
    raw_grade_response: dict | None     # Parsed JSON from LLM
    grade: QuestionGrade | None

    # After verification (if triggered)
    needs_verification: bool
    verification_response: dict | None
    
    # Control
    error: str | None
    attempt: int
```

### Agent Graph

```
START
  │
  ▼
[check_ocr] ──(below threshold)──► [flag_unreadable] ──► END
  │
  (ok)
  │
  ▼
[grade] ──(parse error + retries left)──► [grade]  (self-loop, max 2 attempts)
  │
  (success)
  │
  ▼
[validate_and_route]
  │
  ├──(clean)──────────► [finalize] ──► END
  │
  └──(suspicious)──► [verify] ──► [apply_corrections] ──► [finalize] ──► END
```

**Total: 5 nodes + conditional edges.**

### Node Implementations

```python
from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(model="claude-sonnet-4-20250514", max_tokens=1024)

# ── Node 1: check_ocr ──
def check_ocr(state: GradingState) -> GradingState:
    """If ocr_confidence < policies.ocr_confidence_floor, set needs_verification = False
    and let the conditional edge route to flag_unreadable."""
    # No LLM call. Pure logic.
    return state

# ── Node 2: flag_unreadable ──
def flag_unreadable(state: GradingState) -> GradingState:
    """Build a QuestionGrade with 0 marks, UNREADABLE flag, empty results.
    No LLM call."""
    return state

# ── Node 3: grade ──
async def grade(state: GradingState) -> GradingState:
    """THE MAIN LLM CALL. Builds prompt, calls Claude, parses JSON.
    
    Uses LangChain:
        inputs = format_grading_inputs(state["question"], state["student_text"], ...)
        response = await llm.ainvoke(grade_prompt.format_messages(**inputs))
        parsed = json.loads(response.content)
    
    On JSON parse failure, increment state["attempt"]. The conditional edge
    will loop back if attempt < 2, else route to finalize with LLM_PARSE_ERROR.
    """
    return state

# ── Node 4: validate_and_route ──
def validate_and_route(state: GradingState) -> GradingState:
    """Pure logic — NO LLM call. Checks the grade for suspicious patterns:
    
    Trigger verification if ANY of:
    1. Math mismatch: sum(criterion marks) + sum(penalties) != reported total (tolerance 0.01)
    2. Contradiction: a justification says "student did not address this" but marks > 0
    3. Edge scores: any criterion awarded exactly 0 or exactly max on a question with partial_credit rules
    4. Suspiciously uniform: all criteria get the same marks (possible lazy grading)
    
    If none triggered, set needs_verification = False.
    If any triggered, set needs_verification = True.
    """
    return state

# ── Node 5: verify ──
async def verify(state: GradingState) -> GradingState:
    """CONDITIONAL LLM CALL #2. Only runs if validate_and_route set needs_verification = True.
    
    Sends the original question + student answer + the proposed grade to the verify_prompt.
    Parses the verification response.
    """
    return state

# ── Node 6: apply_corrections ──
def apply_corrections(state: GradingState) -> GradingState:
    """Pure logic — NO LLM call.
    
    If verification verdict == "CORRECTED":
        Update criterion marks per issues_found.
        Recalculate total.
        Update summary.
        Add "MATH_CORRECTED" or "VERIFIED_CORRECTED" flag.
    If verdict == "APPROVED":
        Keep original grade. Add "VERIFIED_APPROVED" flag.
    """
    return state

# ── Node 7: finalize ──
def finalize(state: GradingState) -> GradingState:
    """Pure logic — NO LLM call.
    
    Build the final QuestionGrade object:
    - Recompute total from criterion_results + deduction_results (always trust our math)
    - Clamp to [0, max_marks]
    - Set verified = True if verification was run, False otherwise
    - Ensure student_id, question_id, model info are populated
    """
    return state
```

### Graph Construction

```python
def build_grading_graph() -> StateGraph:
    graph = StateGraph(GradingState)

    # Add nodes
    graph.add_node("check_ocr", check_ocr)
    graph.add_node("flag_unreadable", flag_unreadable)
    graph.add_node("grade", grade)
    graph.add_node("validate_and_route", validate_and_route)
    graph.add_node("verify", verify)
    graph.add_node("apply_corrections", apply_corrections)
    graph.add_node("finalize", finalize)

    # Entry point
    graph.set_entry_point("check_ocr")

    # Conditional: OCR check
    graph.add_conditional_edges("check_ocr", lambda s: "flag_unreadable" if s["ocr_confidence"] < s["policies"].ocr_confidence_floor else "grade")

    # Conditional: grade parse success or retry
    def after_grade(state):
        if state.get("error") == "parse_error" and state["attempt"] < 2:
            return "grade"          # Retry
        if state.get("error") == "parse_error":
            return "finalize"       # Give up, flag LLM_PARSE_ERROR
        return "validate_and_route" # Success
    graph.add_conditional_edges("grade", after_grade)

    # Conditional: needs verification?
    graph.add_conditional_edges("validate_and_route", lambda s: "verify" if s["needs_verification"] else "finalize")

    # Linear edges
    graph.add_edge("flag_unreadable", END)
    graph.add_edge("verify", "apply_corrections")
    graph.add_edge("apply_corrections", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
```

### Runner Function

```python
grading_graph = build_grading_graph()

async def grade_question(
    student_id: str,
    question: Question,
    student_text: str,
    ocr_confidence: float,
    policies: GlobalPolicies,
) -> QuestionGrade:
    """Run the grading graph for one student × one question.
    Returns QuestionGrade extracted from final state."""
    
    initial_state: GradingState = {
        "student_id": student_id,
        "question": question,
        "student_text": student_text,
        "ocr_confidence": ocr_confidence,
        "policies": policies,
        "raw_grade_response": None,
        "grade": None,
        "needs_verification": False,
        "verification_response": None,
        "error": None,
        "attempt": 0,
    }

    final_state = await grading_graph.ainvoke(initial_state)
    return final_state["grade"]
```

---

## Step 5: Batch Orchestrator (`batch.py`)

```python
import asyncio
from collections import defaultdict
from typing import Callable

async def grade_exam(
    rubric: ExamRubric,
    student_answers: list[dict],
    max_concurrency: int = 10,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[StudentExamGrade]:
    """
    Grade all students against the rubric.

    student_answers format:
    [
        {
            "student_id": "STU001",
            "answers": [
                {"question_id": "Q1", "text": "...", "ocr_confidence": 0.85},
                {"question_id": "Q2", "text": "...", "ocr_confidence": 0.72},
            ]
        }
    ]

    - Flatten to (student_id, question, text, confidence) task list.
    - Semaphore(max_concurrency) limits parallel LLM calls.
    - on_progress(completed, total) fires after each task.
    - Group results by student, compute totals, aggregate flags.
    """
    sem = asyncio.Semaphore(max_concurrency)
    question_map = {q.question_id: q for q in rubric.questions}
    total_tasks = sum(len(s["answers"]) for s in student_answers)
    completed = 0

    async def run_one(sid, question, text, confidence):
        nonlocal completed
        async with sem:
            result = await grade_question(sid, question, text, confidence, rubric.policies)
            completed += 1
            if on_progress:
                on_progress(completed, total_tasks)
            return result

    tasks = []
    for student in student_answers:
        for answer in student["answers"]:
            q = question_map[answer["question_id"]]
            tasks.append(run_one(student["student_id"], q, answer["text"], answer["ocr_confidence"]))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Handle exceptions — convert to error grades
    clean_results = []
    for r in results:
        if isinstance(r, Exception):
            # Log error, skip — or create a placeholder grade with SYSTEM_ERROR flag
            continue
        clean_results.append(r)

    # Group by student
    grouped = defaultdict(list)
    for grade in clean_results:
        grouped[grade.student_id].append(grade)

    output = []
    for student_id, grades in grouped.items():
        all_flags = list({f for g in grades for f in g.flags})
        output.append(StudentExamGrade(
            student_id=student_id,
            exam_id=rubric.exam_id,
            question_grades=sorted(grades, key=lambda g: g.question_id),
            total_score=sum(g.total_marks for g in grades),
            max_possible=rubric.total_marks,
            flags=all_flags,
        ))

    return output
```

---

## Step 6: Sample Rubric (`rubrics/sample_rubric.json`)

Create this exact JSON:

```json
{
  "exam_id": "CS201_midsem_2026",
  "course": "Data Structures & Algorithms",
  "total_marks": 23,
  "policies": {
    "partial_credit": true,
    "ocr_confidence_floor": 0.6,
    "abstain_policy": "If the extracted text is unreadable or empty, assign 0 marks to all criteria and set flag UNREADABLE."
  },
  "questions": [
    {
      "question_id": "Q1",
      "question_text": "Explain the time complexity of inserting an element into a balanced BST. Derive the complexity step by step.",
      "max_marks": 10,
      "criteria": [
        {"id": "Q1_C1", "description": "States the final complexity is O(log n)", "marks": 2, "partial_credit": null},
        {"id": "Q1_C2", "description": "Explains that tree height is log(n) because of the balancing invariant", "marks": 3, "partial_credit": "Award 1.5 if height is mentioned but balancing invariant is not explained"},
        {"id": "Q1_C3", "description": "Walks through the traversal: compare at each node, recurse left/right, insert at leaf", "marks": 3, "partial_credit": "Award 1 per step correctly described (compare, recurse, insert)"},
        {"id": "Q1_C4", "description": "Mentions rebalancing (rotations) after insertion is O(1) amortized", "marks": 2, "partial_credit": "Award 1 if rotations mentioned but cost not analyzed"}
      ],
      "deductions": [
        {"condition": "Claims O(n) without specifying this applies only to unbalanced trees", "penalty": -1},
        {"condition": "Confuses BST insertion with heap insertion", "penalty": -2}
      ],
      "alternatives": [
        {"description": "Uses AVL or Red-Black tree specific derivation", "instruction": "Accept as equivalent"}
      ],
      "grader_notes": "Diagrams transcribed as textual steps are acceptable."
    },
    {
      "question_id": "Q2",
      "question_text": "Write a function to detect a cycle in a linked list. Explain your approach.",
      "max_marks": 10,
      "criteria": [
        {"id": "Q2_C1", "description": "Correctly implements or describes Floyd's two-pointer cycle detection", "marks": 4, "partial_credit": "Award 2 if hash-set approach used instead — correct but O(n) space"},
        {"id": "Q2_C2", "description": "Code handles edge cases: empty list, single node, no-cycle termination", "marks": 3, "partial_credit": "Award 1 per edge case handled"},
        {"id": "Q2_C3", "description": "States time O(n) and space O(1) for Floyd's approach", "marks": 3, "partial_credit": "Award 1.5 per correct complexity"}
      ],
      "deductions": [
        {"condition": "Code has infinite loop with no termination condition", "penalty": -2}
      ],
      "alternatives": [
        {"description": "Uses hash set instead of Floyd's", "instruction": "Accept but cap Q2_C1 at 2 marks and adjust Q2_C3 to expect O(n) space"},
        {"description": "Pseudocode instead of specific language", "instruction": "Accept if logic is clear"}
      ],
      "grader_notes": "Any language accepted. Syntax errors alone should not lose marks if logic is sound."
    },
    {
      "question_id": "Q3",
      "question_text": "What is the time complexity of BFS on a graph with V vertices and E edges?",
      "max_marks": 3,
      "criteria": [
        {"id": "Q3_C1", "description": "Correct answer: O(V + E)", "marks": 3, "partial_credit": "Award 1 if only O(V) or only O(E) stated. Award 2 if O(V+E) stated with incorrect justification."}
      ],
      "deductions": [],
      "alternatives": [],
      "grader_notes": null
    }
  ]
}
```

---

## Step 7: Tests

### `test_validator.py`
- Valid rubric loads without errors.
- Mismatched criteria marks produce warning.
- Duplicate criterion IDs produce warning.
- `normalize_rubric` deduplicates IDs.

### `test_grading_agent.py`

Mock the LLM using `unittest.mock.patch` on the `ChatAnthropic.ainvoke` method. Do NOT call the real API.

- **Full marks path**: Mock LLM returns perfect grade JSON → verify QuestionGrade has correct scores, `verified=False`, no flags.
- **Partial marks path**: Mock LLM returns partial marks → verify math is correct.
- **Verification trigger**: Mock LLM returns grade where justification contradicts marks (says "student did not address" but awards full marks) → verify the graph routes to `verify` node → mock second LLM call returns correction → verify final grade is corrected and `verified=True`.
- **Parse failure**: Mock LLM returns non-JSON → verify retry fires → second attempt also fails → verify `LLM_PARSE_ERROR` flag and 0 marks.
- **Low OCR**: Set ocr_confidence=0.3 → verify graph routes to `flag_unreadable`, no LLM calls made, `UNREADABLE` flag set.

### `test_batch.py`
- 3 students × 3 questions = 9 tasks. All succeed. Verify 3 StudentExamGrades with correct totals.
- 1 task throws exception. Other 8 succeed. Verify partial results returned.
- Progress callback fires correct number of times.

---

## Step 8: README.md

Include:
- One-paragraph description.
- Setup: `pip install -r requirements.txt`, set `ANTHROPIC_API_KEY`.
- Usage example: load rubric → prepare student_answers list → `await grade_exam(rubric, answers)` → print results.
- Architecture diagram (ASCII):

```
┌─────────┐    ┌───────┐    ┌────────────────────┐    ┌────────┐
│check_ocr│───►│ grade │───►│ validate_and_route  │───►│finalize│──► END
└────┬────┘    └───┬───┘    └─────────┬──────────-┘    └────────┘
     │              │                  │
     │(low)         │(parse fail)      │(suspicious)
     ▼              ▼                  ▼
┌───────────┐   [retry or          ┌────────┐    ┌──────────────┐
│flag_unread│    finalize w/       │ verify │───►│apply_correct.│──► finalize
│  able     │    PARSE_ERROR]      └────────┘    └──────────────┘
└───────────┘
```

- Cost estimate: `students × questions × $0.004-0.008` (1 call happy path, 2 calls if verified).

---

## Requirements

```
langchain-core>=0.3.0
langchain-anthropic>=0.3.0
langgraph>=0.2.0
pydantic>=2.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

---

## Build Order

1. `schema.py` — All Pydantic models
2. `rubrics/sample_rubric.json` — Sample data
3. `validator.py` + `test_validator.py` — Load and validate
4. `prompts.py` — Both prompt templates + format helpers
5. `grading_agent.py` + `test_grading_agent.py` — LangGraph agent with all nodes
6. `batch.py` + `test_batch.py` — Concurrent execution
7. `README.md`

---

## Quality Gates

- [ ] `sample_rubric.json` loads into `ExamRubric` cleanly
- [ ] `validate_rubric` catches at least 3 warning types
- [ ] Happy path: 1 LLM call, correct QuestionGrade output
- [ ] Verification triggers on math mismatch or justification contradiction
- [ ] Verification never triggers on a clean grade (no unnecessary second calls)
- [ ] Parse failure retries once, then flags LLM_PARSE_ERROR
- [ ] Low OCR skips LLM entirely, returns UNREADABLE
- [ ] Batch handles concurrent tasks with semaphore, returns partial results on failure
- [ ] All tests pass with `pytest -v`
