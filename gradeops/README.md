# GradeOps — Rubric Engine (Module 2)

LLM-driven grading pipeline that turns OCR-extracted exam answers and a structured rubric into validated, justified grades. Built on LangGraph + Google Gemini, with a conditional verification step so the LLM is only called a second time when the first response looks suspicious.

## Setup

```bash
pip install -r requirements.txt
```

Drop your Gemini API key in `.env` at the repo root:

```
GEMINI_API_KEY = 'your-key-here';
```

(The loader tolerates the `KEY = 'value';` format with spaces and trailing semicolons.) Python 3.11+ is required.

## Run the end-to-end demo

```bash
.venv/bin/python -m gradeops.run_demo
```

This loads `gradeops/rubrics/sample_rubric.json`, runs three sample students (strong, partial, unreadable) × three questions through real Gemini calls, and prints per-criterion grades with justifications. Add `--json` for machine-readable output, `--concurrency N` to fan out wider.

## Web UI (Streamlit)

```bash
/Users/zeeshan/Library/Caches/gradeops-venv/bin/streamlit run app.py
```

Opens a browser at `http://localhost:8501`. Upload a rubric JSON and student answers — CSV, JSON, **or scanned PDFs** — or click **Use sample** to load everything in one click. Sample files live in `gradeops/samples/`:

- **CSV** — `student_id, question_id, text, ocr_confidence` (one row per answer).
- **JSON** — nested `[{ student_id, answers: [...] }]` matching `grade_exam`'s input.
- **PDFs (scanned)** — drop one PDF per `student_id`+`question_id`. The filename convention is `STU001_Q1.pdf` (regenerate the sample set with `python gradeops/samples/generate_sample_pdfs.py`).

The UI surfaces per-student totals, per-criterion justifications, verification flags, and exposes JSON + flattened-CSV downloads of the graded results. Pick a stricter or cheaper Gemini model from the sidebar; the change takes effect on the next OCR or grading run.

### Scanned PDFs via Gemini Vision

When you choose the **PDFs (scanned)** format the app:

1. Parses the filenames (must match `{student_id}_{question_id}.pdf`) and shows a ready/error table.
2. Renders each PDF page to a 200 DPI PNG and sends the images to Gemini Vision with an extraction prompt. Each PDF costs one Gemini call here.
3. Derives `ocr_confidence` heuristically (`0.9` clean, `0.55` if the model marked any region `[illegible]`, `0.0` if blank) — the grading pipeline then routes the latter two to `LOW_OCR_CONFIDENCE` / `UNREADABLE` automatically.
4. Folds the per-file extractions back into the same `{ student_id, answers }` shape the rest of the pipeline already understands, so grading proceeds unchanged.

Click **Use sample PDFs** in the UI to skip uploads and load the 9 bundled samples.


## Specialized OCR engines

Three engines are wired in. Each appears in the sidebar **PDF OCR engine** radio only when its credentials are detected.

### Google Cloud Vision (handwriting)

Google's `DOCUMENT_TEXT_DETECTION` feature is tuned for dense / handwritten text — meaningfully better than Gemini Vision on a messy exam scan.

1. In your GCP console, **enable the Cloud Vision API** for the project.
2. Authenticate either by running `gcloud auth application-default login` once, **or** by pointing `GOOGLE_APPLICATION_CREDENTIALS` at a service-account JSON. The same credentials work for GCS, so configure it once and both backends light up.
3. Restart Streamlit. A **Google Cloud Vision (handwriting)** option appears under **PDF OCR engine**.

`ocr_confidence` is the mean of all word-level confidences GCV reports — a real number, not a heuristic. Pricing: first **1000 pages/month free**, then $1.50 per 1000 pages.

### Mathpix (handwriting + STEM math)

[Mathpix](https://mathpix.com) is purpose-built for STEM handwriting and returns math wrapped in `$…$` LaTeX delimiters — useful when answers contain equations, integrals, matrices, etc.

1. Sign up at https://accounts.mathpix.com/.
2. Copy `MATHPIX_APP_ID` and `MATHPIX_APP_KEY` into `.env`.
3. Restart Streamlit. A **Mathpix (handwriting + math)** option appears under **PDF OCR engine**.

Each PDF page = 1 Mathpix request. The free tier is currently ~1000 pages/month. Mathpix returns a real per-image `confidence` score (0..1) — we use that directly.

## Cloud storage — Google Cloud Storage

Set `GCS_BUCKET` in `.env` to flip storage from the local filesystem to GCS. Authentication is whatever the [`google-cloud-storage`](https://cloud.google.com/python/docs/reference/storage/latest) client finds first — either:

- **Application Default Credentials** (run `gcloud auth application-default login` once), or
- A service-account JSON file pointed to by `GOOGLE_APPLICATION_CREDENTIALS`.

```
GCS_BUCKET = 'gradeops-prod'
GCS_PREFIX = 'gradeops'                     # optional, defaults to 'gradeops'
GOOGLE_APPLICATION_CREDENTIALS = '/abs/path/to/service-account.json'
```

When the **Auto-save OCR + grades** checkbox is on (sidebar, default ON), every demo run writes:

```
<bucket>/<prefix>/<exam_id>/pdfs/STU###_Q#.pdf      ← raw scanned PDFs
<bucket>/<prefix>/<exam_id>/ocr/STU###_Q#.json      ← extracted text + engine + confidence
<bucket>/<prefix>/<exam_id>/grades/STU###.json      ← per-student grade
<bucket>/<prefix>/<exam_id>/grades_all.json         ← combined run
```

The same layout is used by the local backend (under `gradeops/storage/`), so you can develop offline and switch to GCS later with no code changes.

## Quick start (library use)

```python
import asyncio
from gradeops.rubric_engine import grade_exam, load_rubric
from gradeops.rubric_engine.config import load_env

load_env()  # picks up GEMINI_API_KEY from ./.env

rubric = load_rubric("gradeops/rubrics/sample_rubric.json")

student_answers = [
    {
        "student_id": "STU001",
        "answers": [
            {"question_id": "Q1", "text": "Inserting into a balanced BST takes O(log n) because...", "ocr_confidence": 0.92},
            {"question_id": "Q2", "text": "I'll use Floyd's two pointers...", "ocr_confidence": 0.88},
            {"question_id": "Q3", "text": "BFS is O(V + E).", "ocr_confidence": 0.95},
        ],
    },
]

def progress(done, total):
    print(f"{done}/{total} graded")

results = asyncio.run(grade_exam(rubric, student_answers, max_concurrency=5, on_progress=progress))

for student in results:
    print(f"\n{student.student_id}: {student.total_score} / {student.max_possible}")
    for grade in student.question_grades:
        print(f"  {grade.question_id}: {grade.total_marks}/{grade.max_marks}  flags={grade.flags}")
        print(f"    {grade.summary}")
```

## Architecture

```
┌─────────┐    ┌───────┐    ┌────────────────────┐    ┌────────┐
│check_ocr│───►│ grade │───►│ validate_and_route │───►│finalize│──► END
└────┬────┘    └───┬───┘    └─────────┬──────────┘    └────────┘
     │             │                  │
     │(low)        │(parse fail)      │(suspicious)
     ▼             ▼                  ▼
┌───────────┐   [retry or          ┌────────┐    ┌──────────────┐
│flag_unread│    finalize w/       │ verify │───►│apply_correct.│──► finalize
│  able     │    PARSE_ERROR]      └────────┘    └──────────────┘
└───────────┘
```

### LLM call budget
- **Happy path: 1 call.** `grade` evaluates every criterion, every deduction, totals, and summary in one shot.
- **Verification path: 2 calls.** `verify` only fires when `validate_and_route` detects something suspicious (math mismatch, justification contradicting marks, edge scores on partial-credit criteria, or suspiciously uniform marks).
- **Hard cap: 2 calls.** Parse retries swap the failed call for a new one — they don't stack on top.

### Suspicion triggers (no LLM cost)
`validate_and_route` is pure logic. It flags a grade for verification if any of:
1. `sum(criterion_marks) + sum(applied_penalties)` differs from `total_marks` by more than 0.01.
2. A justification contains "did not address / mention / answer" style phrasing but marks > 0.
3. A *mix* of partial-credit criteria where some are at edge scores (0 or max) and others aren't — suggests the LLM ignored partial-credit rules for some criteria. Uniform 0% or 100% across all partial-credit criteria is treated as consistent, not suspicious.
4. Every criterion gets the same intermediate fraction of its max (lazy 60%-for-everything grading). Uniform 0% / 100% is exempted for the same reason.

### Flags emitted
- `UNREADABLE` — answer empty or OCR below the floor.
- `LOW_OCR_CONFIDENCE` — OCR confidence below `policies.ocr_confidence_floor`.
- `LLM_PARSE_ERROR` — both grade attempts failed to produce valid JSON.
- `NEEDS_REVIEW` — some criterion was missing from the LLM response or another anomaly was logged.
- `VERIFIED_APPROVED` — verification ran and confirmed the original grade.
- `VERIFIED_CORRECTED` / `MATH_CORRECTED` — verification ran and changed the grade.

## Project layout

```
GradeOPS/
├── app.py                       # Streamlit frontend (project root)
├── .env                         # GEMINI_API_KEY
└── gradeops/
    ├── rubric_engine/
    │   ├── __init__.py
    │   ├── schema.py            # Pydantic models
    │   ├── validator.py         # load / validate / normalize
    │   ├── config.py            # .env loader
    │   ├── prompts.py           # Grade + verify templates and formatters
    │   ├── grading_agent.py     # LangGraph state machine + set_model()
    │   ├── batch.py             # asyncio.Semaphore-bounded fan-out
    │   ├── pdf_ocr.py           # Gemini-vision PDF extractor
    │   └── utils.py             # JSON extraction, math check, suspicion detection
    ├── rubrics/
    │   └── sample_rubric.json   # CS201 midsem example
    ├── samples/
    │   ├── sample_students.json     # Demo answers (JSON shape)
    │   ├── sample_students.csv      # Same in CSV shape
    │   ├── generate_sample_pdfs.py  # Builder for the bundled PDFs
    │   └── pdfs/                    # 9 sample exam PDFs (STU###_Q#.pdf)
    ├── tests/
    │   ├── test_validator.py
    │   ├── test_grading_agent.py
    │   └── test_batch.py
    ├── run_demo.py              # End-to-end CLI runner
    └── requirements.txt
```

## Running tests

```bash
cd gradeops
pytest -v
```

All tests mock `ChatAnthropic.ainvoke` — no API key is needed and no real LLM calls are made.

## Cost estimate

At Gemini 2.0 Flash list pricing, each grading cycle is on the order of **$0.0005 – $0.001**:
- Happy path: ~1.5K input tokens + ~500 output tokens ≈ ~$0.0005 / question.
- Verified path: about twice that.

For an exam with `S` students × `Q` questions: `total_cost ≈ S × Q × 0.0005` if no verification fires, scaling up as the verification rate climbs. Bump to Gemini 1.5/2.5 Pro by setting `GEMINI_MODEL=gemini-2.5-pro` if you want stricter grading at higher cost.

## Integration points

- **Inputs** (from Module 1 — OCR pipeline): a list of student answers shaped as
  `{"student_id": str, "answers": [{"question_id": str, "text": str, "ocr_confidence": float}]}`.
- **Outputs** (to Module 4 — TA review dashboard): `list[StudentExamGrade]`, each containing per-question `QuestionGrade` objects with criterion-level justifications, deduction breakdowns, and review flags.
