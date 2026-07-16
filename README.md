# GradeOps

Human-in-the-loop exam grading platform. Instructors upload scanned exam PDFs
and a structured rubric; a Vision-Language Model extracts the handwritten
text; a LangGraph agent awards partial credit with structured justifications;
and a TA review dashboard with keyboard shortcuts lets graders confirm or
override every decision.

## What it does

Mapped to the original GradeOps problem statement:

- **Bulk PDF upload + JSON rubric.** Instructors create exams from a rubric
  JSON and upload per-student PDFs in one batch. Filenames like
  `STU001.pdf` (per-student) or `STU001_Q1.pdf` (per-question) are auto-routed.
- **Role-Based Access Control.** Two roles: `INSTRUCTOR` and `TA`. JWT tokens
  carry the role, FastAPI dependencies enforce it on every route. Accounts
  live in PostgreSQL with bcrypt-hashed passwords.
- **OCR / VLM extraction.** Pluggable. Default is Google Gemini Vision.
  `facebook/nougat-small` is wired up in a separate `ml-worker` container,
  enabled with `docker compose --profile ml`. OCR'd PDFs are stored in
  Google Cloud Storage; only the logical key is persisted in Postgres.
- **Agentic LLM pipeline.** A LangGraph state graph (`extract → grade per
  question → validate → verify → finalise`). Each criterion produces a numeric
  mark and a natural-language justification grounded in the student's text.
- **Plagiarism flagging.** Per-question cosine similarity over word-bag
  vectors of the OCR text. Pairs at or above 0.65 are persisted and surfaced
  to the TA.
- **TA review dashboard.** Two-pane layout: PDF cropped to the question's page
  via PDF.js fragment navigation, AI grade and justification on the right.
  Keyboard shortcuts (`A` approve, `O` override, `F` flag, `← →` navigate)
  for high-throughput review.

## Stack

| Layer | Tech |
| --- | --- |
| Backend | FastAPI 0.115, SQLAlchemy 2.0 (async), Alembic, pydantic v2 |
| Database | PostgreSQL 16 |
| Object storage | Google Cloud Storage (or local disk) |
| ML — OCR | Google Gemini Vision, or `facebook/nougat-small` via Hugging Face |
| ML — grading | LangGraph + LangChain, Gemini 2.5 Flash Lite |
| Frontend | React 18, Vite 6, TypeScript 5, Tailwind 3, react-router 6 |
| Auth | JWT (HS256, 24h), bcrypt password hashing |
| Orchestration | Docker Compose |

## Quick start

### Prerequisites

- Docker Desktop (Compose v2)
- Node 20+ and npm (for the frontend dev server)
- A Gemini API key (https://aistudio.google.com/app/apikey)
- Optional: a GCP service-account JSON for Cloud Storage. Local-disk storage
  works fine if you skip this.

### Configure

```bash
git clone <this-repo> GradeOps
cd GradeOps

# Backend environment
cp backend/.env.example backend/.env   # if you ship a template; otherwise edit directly
# Then set at minimum:
#   GEMINI_API_KEY=...
#   SECRET_KEY=<generate a random one>
#   STORAGE_BACKEND=local      # or 'gcs'
#   GCS_BUCKET=<your bucket>   # if STORAGE_BACKEND=gcs
#   DEMO_MODE=false
#   OCR_ENGINE=gemini          # or 'nougat' (requires the ml-worker profile)

# If using GCS, drop the service-account JSON at the repo root
# (docker-compose mounts it into the backend container).
cp /path/to/service-account.json google_storage.json
```

`backend/.env`, `.env`, and `google_storage.json` are gitignored — they will
never be committed.

### Bring up the stack

```bash
# Core stack: db + backend
docker compose up -d db backend

# Optional: nougat OCR worker (Hugging Face + Torch CPU)
docker compose --profile ml up -d ml-worker

# Frontend dev server
cd frontend && npm install && npm run dev
```

Open http://localhost:5173.

### Seeded accounts

| Role | Email | Password |
| --- | --- | --- |
| Instructor | `instructor@gradeops.dev` | `instructor123` |
| TA | `ta@gradeops.dev` | `ta12345678` |

Both are created by the first Alembic migration. Change them, or register new
users at `POST /api/v1/auth/register`.

### Try it with sample data

```bash
# Regenerate sample PDFs (writes samples/pdfs/*)
docker run --rm -v "$PWD/samples:/work" -w /work gradeops-ml-worker \
  python /work/generate_sample_pdfs.py
# (Or run directly if PyMuPDF is installed on the host.)
```

In the UI: log in as instructor, create an exam from [samples/sample_rubric.json](samples/sample_rubric.json),
upload the four `samples/pdfs/STU*.pdf` files, hit **Run grading**. Then log
in as TA in a second browser to see the review queue.

## Repo layout

```
.
├── backend/                FastAPI backend (async SQLAlchemy + Alembic)
│   ├── app/api/v1/         Routes: auth, users, exams, reviews
│   ├── app/services/       grading, ocr_client, storage, plagiarism, demo_grading
│   ├── app/models/         SQLAlchemy models
│   └── alembic/versions/   Migrations
├── frontend/               React + Vite + TS
│   └── src/pages/          LoginPage, ExamsPage, ExamDetailPage, ReviewPage, ...
├── gradeops/               Original grading engine (LangGraph + Gemini)
│   └── rubric_engine/      grading_agent.py (LangGraph), pdf_ocr.py, prompts.py
├── ml-worker/              Hugging Face OCR container (nougat-small)
│   ├── Dockerfile          torch CPU + transformers + nougat pre-cached
│   └── app.py              FastAPI exposing /ocr/nougat
├── samples/                Sample rubric, student answers, generator script
└── docker-compose.yml      db + backend + ml-worker (profile-gated)
```

## Environment

Backend reads `backend/.env` via pydantic-settings. Key variables:

| Var | Purpose | Default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Auth for Gemini Vision + LangChain | required (unless `DEMO_MODE=true`) |
| `GEMINI_MODEL` | Gemini model id | `gemini-2.5-flash-lite` |
| `SECRET_KEY` | JWT signing key | required |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime | `1440` (24 h) |
| `POSTGRES_*` | DB connection | configured for docker compose |
| `STORAGE_BACKEND` | `local` or `gcs` | `local` |
| `GCS_BUCKET`, `GCS_PREFIX` | GCS location | required if `STORAGE_BACKEND=gcs` |
| `OCR_ENGINE` | `gemini` or `nougat` | `gemini` |
| `ML_WORKER_URL` | nougat worker URL | `http://ml-worker:8001` |
| `DEMO_MODE` | Bypass OCR + LLM, synthesize grades | `false` |

Changing `backend/.env` requires a container recreate:

```bash
docker compose up -d --force-recreate backend
```

## Switching OCR engines

```bash
# Real Gemini OCR (default)
# backend/.env: OCR_ENGINE=gemini
docker compose up -d --force-recreate backend

# Hugging Face nougat-small via the ml-worker container
docker compose --profile ml up -d ml-worker
# backend/.env: OCR_ENGINE=nougat
docker compose up -d --force-recreate backend
```

nougat-small runs on CPU and takes roughly 7–25 seconds per page. The model
weights (~250 MB) are pre-cached into the Docker image at build time.

## API tour

| Method | Path | Role | What it does |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/login` | any | OAuth2 form auth, returns JWT |
| `POST` | `/api/v1/exams` | instructor | Create exam from rubric JSON |
| `POST` | `/api/v1/exams/{id}/pdfs` | any | Upload one or many PDFs |
| `POST` | `/api/v1/exams/{id}/grade` | instructor | Run OCR + grading + plagiarism |
| `GET` | `/api/v1/exams/{id}/grades` | any | Latest grading run + per-student grades |
| `GET` | `/api/v1/exams/{id}/plagiarism` | any | Suspicious pairs from latest run |
| `GET` | `/api/v1/exams/{id}/review/queue` | TA | Items for the review dashboard |
| `POST` | `/api/v1/grades/{grade_id}/review` | TA | Approve / override / flag a question |

Full schema at http://localhost:8000/docs once the backend is running.

## Tests

```bash
# Backend
cd backend && pytest

# Frontend type check + lint
cd frontend && npm run build
```

## License

Internal project. No license file shipped.
