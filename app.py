"""Streamlit frontend for the GradeOps Rubric Engine.

Run with:
    .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

# Load .env before any module-level LLM client is constructed.
from gradeops.rubric_engine.config import load_env

load_env()

from gradeops.rubric_engine import grade_exam, validate_rubric  # noqa: E402
from gradeops.rubric_engine.grading_agent import DEFAULT_MODEL, set_model  # noqa: E402
from gradeops.rubric_engine.pdf_ocr import (  # noqa: E402
    extract_from_pdfs,
    group_by_student,
    parse_filename,
)
from gradeops.rubric_engine.schema import ExamRubric  # noqa: E402
from gradeops.rubric_engine.storage import (  # noqa: E402
    get_storage,
    persist_extractions,
    persist_grades,
)


def _mathpix_creds_present() -> bool:
    import os

    return bool(os.environ.get("MATHPIX_APP_ID") and os.environ.get("MATHPIX_APP_KEY"))


def _gcs_creds_present() -> bool:
    import os

    return bool(os.environ.get("GCS_BUCKET"))


def _gcv_creds_present() -> bool:
    """True when Google Cloud Vision is importable AND some form of credentials
    is discoverable. We don't actually instantiate the client here — that's
    deferred to the first OCR call so import-time stays cheap."""
    import os

    try:
        from google.cloud import vision  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return adc.is_file()


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit setup
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="GradeOps", layout="wide")
st.title("GradeOps")
st.caption(
    "Grade student answers against a rubric using Google Gemini. "
    "Upload a rubric and scanned student PDFs, then press **Start grading**. "
    "Suspicious grades (math mismatch, contradiction) are automatically "
    "re-checked by a second verification pass."
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_rubric(content: bytes) -> tuple[ExamRubric, list[str]]:
    data = json.loads(content)
    rubric = ExamRubric.model_validate(data)
    warnings = validate_rubric(rubric)
    return rubric, warnings


def _flag_badge(flag: str) -> str:
    color = {
        "UNREADABLE": "red",
        "LOW_OCR_CONFIDENCE": "orange",
        "LLM_PARSE_ERROR": "red",
        "LLM_API_ERROR": "red",
        "NEEDS_REVIEW": "orange",
        "VERIFIED_APPROVED": "green",
        "VERIFIED_CORRECTED": "blue",
        "MATH_CORRECTED": "blue",
    }.get(flag, "gray")
    return f":{color}[**{flag}**]"


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — settings
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")
    model = st.text_input(
        "Gemini model",
        value=DEFAULT_MODEL,
        help="Try gemini-2.5-flash-lite (default), gemini-2.5-flash, or gemini-2.5-pro.",
    )
    concurrency = st.slider(
        "Max concurrency",
        min_value=1,
        max_value=10,
        value=2,
        help="Parallel API calls. Keep low on the free tier to avoid 429s.",
    )

    st.divider()
    st.subheader("PDF OCR engine")
    mathpix_available = _mathpix_creds_present()
    gcv_available = _gcv_creds_present()

    ocr_engine_options = ["Gemini Vision"]
    if gcv_available:
        ocr_engine_options.append("Google Cloud Vision (handwriting)")
    if mathpix_available:
        ocr_engine_options.append("Mathpix (handwriting + math)")

    ocr_engine_label = st.radio(
        "Choose engine",
        options=ocr_engine_options,
        help=(
            "Gemini Vision is the default. Google Cloud Vision uses the DOCUMENT_TEXT_DETECTION "
            "feature (tuned for handwriting). Mathpix is purpose-built for STEM math + handwriting."
        ),
    )
    if ocr_engine_label.startswith("Mathpix"):
        ocr_engine = "mathpix"
        default_dpi = 300
    elif ocr_engine_label.startswith("Google Cloud Vision"):
        ocr_engine = "gcv"
        default_dpi = 300
    else:
        ocr_engine = "gemini"
        default_dpi = 200

    ocr_dpi = st.slider(
        "Render DPI",
        min_value=150,
        max_value=400,
        value=default_dpi,
        step=50,
        help="Higher DPI is slower but materially better on messy handwriting.",
    )

    missing = []
    if not gcv_available:
        missing.append(
            "Google Cloud Vision locked — run `gcloud auth application-default login` "
            "or set `GOOGLE_APPLICATION_CREDENTIALS` in `.env`."
        )
    if not mathpix_available:
        missing.append(
            "Mathpix locked — set `MATHPIX_APP_ID` and `MATHPIX_APP_KEY` in `.env`."
        )
    for line in missing:
        st.caption(line)

    st.divider()
    st.subheader("Storage")
    gcs_available = _gcs_creds_present()
    storage_options = ["Local filesystem"]
    if gcs_available:
        storage_options.insert(0, "Google Cloud Storage")
    storage_label = st.radio(
        "Backend",
        options=storage_options,
        help="Where to save uploaded PDFs, OCR results, and graded outputs.",
    )
    storage_choice = "gcs" if storage_label.startswith("Google Cloud") else "local"
    if not gcs_available:
        st.caption(
            "GCS locked — set `GCS_BUCKET` (and `GOOGLE_APPLICATION_CREDENTIALS` "
            "for the service account) in `.env`."
        )

    persist_to_storage = st.checkbox(
        "Auto-save OCR + grades after each run",
        value=True,
        help=(
            "Writes the raw PDF, OCR-extracted text, and graded results to the "
            "selected backend under {exam_id}/..."
        ),
    )

    st.divider()
    st.caption(
        "API key is loaded from `.env` (`GEMINI_API_KEY`). "
        "Set `GEMINI_MODEL` env var to change the default."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Rubric
# ─────────────────────────────────────────────────────────────────────────────

st.header("Step 1 — Upload rubric")

rubric_file = st.file_uploader(
    "Rubric JSON",
    type=["json"],
    key="rubric_uploader",
    help="The rubric defines the questions, criteria, and total marks.",
)

rubric: ExamRubric | None = None
warnings: list[str] = []

if rubric_file is not None:
    try:
        rubric, warnings = _parse_rubric(rubric_file.read())
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not parse rubric: {exc}")

if rubric is not None:
    st.success(f"Loaded **{rubric.exam_id}** — {rubric.course}")
    metrics = st.columns(4)
    metrics[0].metric("Total marks", f"{rubric.total_marks:.0f}")
    metrics[1].metric("Questions", len(rubric.questions))
    metrics[2].metric("Criteria", sum(len(q.criteria) for q in rubric.questions))
    metrics[3].metric("Warnings", len(warnings))
    if warnings:
        with st.expander("Validator warnings", expanded=False):
            for w in warnings:
                st.warning(w)
    with st.expander("Rubric details (JSON)", expanded=False):
        st.json(rubric.model_dump())


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Student answers
# ─────────────────────────────────────────────────────────────────────────────

st.header("Step 2 — Upload student PDFs")
st.markdown(
    "**Filename convention:** `{student_id}_{question_id}.pdf` "
    "(e.g. `STU001_Q1.pdf`). Each PDF is sent to the OCR engine; the extracted "
    "text becomes the student's answer."
)

student_answers: list[dict] | None = st.session_state.get("student_answers")

pdf_files = st.file_uploader(
    "Student PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    key="ans_pdf_uploader",
)

pending_pdfs: list[tuple[str, bytes]] = []
if pdf_files:
    for f in pdf_files:
        pending_pdfs.append((f.name, f.read()))

if pending_pdfs:
    # Show what the filenames parse to before we spend any LLM calls.
    parsed_preview = []
    ok_count = 0
    for name, _ in pending_pdfs:
        parsed = parse_filename(name)
        if parsed:
            ok_count += 1
            parsed_preview.append(
                {
                    "filename": name,
                    "student_id": parsed[0],
                    "question_id": parsed[1],
                    "status": "ready",
                }
            )
        else:
            parsed_preview.append(
                {
                    "filename": name,
                    "student_id": "—",
                    "question_id": "—",
                    "status": "bad filename",
                }
            )
    st.dataframe(
        pd.DataFrame(parsed_preview),
        use_container_width=True,
        hide_index=True,
    )

    if ok_count == 0:
        st.error(
            "No PDFs match the `STU###_Q#.pdf` pattern. Rename your files and try again."
        )
    elif st.button(
        f"Extract text from {ok_count} PDFs ({ocr_engine_label})",
        type="secondary",
    ):
        set_model(model)  # honor sidebar setting for OCR too
        from gradeops.rubric_engine import grading_agent as _ga

        ocr_progress = st.progress(0.0)
        ocr_status = st.empty()

        def _on_ocr_progress(done: int, tot: int) -> None:
            ocr_progress.progress(done / tot)
            ocr_status.text(f"Extracted {done}/{tot} pages")

        try:
            with st.spinner(f"Running {ocr_engine_label} OCR on {ok_count} PDFs…"):
                extractions = asyncio.run(
                    extract_from_pdfs(
                        pending_pdfs,
                        llm=_ga.llm if ocr_engine == "gemini" else None,
                        engine=ocr_engine,
                        dpi=ocr_dpi,
                        max_concurrency=concurrency,
                        on_progress=_on_ocr_progress,
                    )
                )
            st.session_state["pdf_extractions"] = extractions

            # Auto-persist raw PDFs + OCR JSON if storage is enabled
            if persist_to_storage and rubric is not None:
                try:
                    storage = get_storage(prefer=storage_choice)
                    keys = persist_extractions(
                        storage,
                        exam_id=rubric.exam_id,
                        extractions=extractions,
                    )
                    st.session_state["storage_location"] = storage.location
                    st.success(
                        f"Saved {len(keys)} OCR objects to **{storage.location}**"
                    )
                except Exception as save_exc:  # noqa: BLE001
                    st.warning(f"Storage save failed (OCR step): {save_exc}")
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
        finally:
            ocr_progress.empty()
            ocr_status.empty()

extractions = st.session_state.get("pdf_extractions")
if extractions:
    errs = [e for e in extractions if "error" in e]
    oks = [e for e in extractions if "error" not in e]
    if errs:
        st.warning(f"{len(errs)} file(s) failed:")
        for e in errs:
            st.markdown(f"  - **{e['filename']}** — {e['error']}")

    if oks:
        with st.expander(
            f"Extracted text ({len(oks)} answers) — review before grading",
            expanded=True,
        ):
            rows = []
            for ext in oks:
                text = ext["text"]
                rows.append(
                    {
                        "student_id": ext["student_id"],
                        "question_id": ext["question_id"],
                        "ocr_confidence": round(ext["ocr_confidence"], 2),
                        "extracted text (preview)": (text[:120] + "…")
                        if len(text) > 120
                        else text or "[empty]",
                    }
                )
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )

        student_answers = group_by_student(oks)
        st.session_state["student_answers"] = student_answers

if student_answers:
    total_tasks = sum(len(s["answers"]) for s in student_answers)
    st.success(
        f"**{len(student_answers)}** students • **{total_tasks}** answers ready for grading"
    )
    with st.expander("Preview parsed answers", expanded=False):
        preview_rows = []
        for s in student_answers:
            for a in s["answers"]:
                preview_rows.append(
                    {
                        "student_id": s["student_id"],
                        "question_id": a["question_id"],
                        "ocr_confidence": a["ocr_confidence"],
                        "text (preview)": (a["text"][:80] + "…")
                        if len(a["text"]) > 80
                        else a["text"],
                    }
                )
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Grade
# ─────────────────────────────────────────────────────────────────────────────

st.header("Step 3 — Grade")

ready = rubric is not None and student_answers is not None
if not ready:
    st.info("Upload a rubric and extract text from student PDFs above to enable grading.")

if "results" not in st.session_state:
    st.session_state.results = None

if st.button("Start grading", type="primary", disabled=not ready):
    set_model(model)
    progress = st.progress(0.0)
    status = st.empty()

    def on_progress(done: int, tot: int) -> None:
        progress.progress(done / tot)
        status.text(f"{done}/{tot} graded")

    try:
        with st.spinner(f"Calling {model}…"):
            results = asyncio.run(
                grade_exam(
                    rubric,
                    student_answers,
                    max_concurrency=concurrency,
                    on_progress=on_progress,
                )
            )
        progress.empty()
        status.empty()
        st.session_state.results = results
        st.success(f"Graded {len(results)} student(s) — see results below.")

        if persist_to_storage and rubric is not None:
            try:
                storage = get_storage(prefer=storage_choice)
                grade_keys = persist_grades(storage, rubric.exam_id, results)
                st.session_state["storage_location"] = storage.location
                st.info(
                    f"Saved {len(grade_keys)} grade objects to **{storage.location}**"
                )
            except Exception as save_exc:  # noqa: BLE001
                st.warning(f"Storage save failed (grading step): {save_exc}")
    except Exception as exc:  # noqa: BLE001
        progress.empty()
        status.empty()
        st.session_state.results = None
        st.exception(exc)

results = st.session_state.results

if results:
    st.header("Step 4 — Results")

    total_students = len(results)
    total_score = sum(r.total_score for r in results)
    max_possible = sum(r.max_possible for r in results)
    needs_review = sum(1 for r in results if "NEEDS_REVIEW" in r.flags)
    verified = sum(1 for r in results if any("VERIFIED" in f for f in r.flags))

    m = st.columns(4)
    m[0].metric("Students graded", total_students)
    m[1].metric("Total score", f"{total_score:.1f} / {max_possible:.0f}")
    m[2].metric("Verified by 2nd call", verified)
    m[3].metric("Need TA review", needs_review)

    for student in results:
        score_pct = (
            (student.total_score / student.max_possible * 100)
            if student.max_possible
            else 0.0
        )
        header = (
            f"**{student.student_id}** — "
            f"{student.total_score:.1f} / {student.max_possible:.0f} "
            f"({score_pct:.0f}%)"
        )
        with st.expander(header, expanded=False):
            if student.flags:
                st.markdown("**Flags:** " + " ".join(_flag_badge(f) for f in student.flags))
            for g in student.question_grades:
                cols = st.columns([1, 4])
                with cols[0]:
                    st.metric(
                        g.question_id,
                        f"{g.total_marks:.1f}/{g.max_marks:.0f}",
                        delta="verified" if g.verified else None,
                    )
                with cols[1]:
                    st.markdown(f"*{g.summary}*")
                    if g.flags:
                        st.markdown(" ".join(_flag_badge(f) for f in g.flags))
                    for cr in g.criterion_results:
                        st.markdown(
                            f"• **{cr.criterion_id}**: "
                            f"`{cr.marks_awarded:.1f}` — {cr.justification}"
                        )
                    if any(dr.applied for dr in g.deduction_results):
                        st.markdown("**Deductions applied:**")
                        for dr in g.deduction_results:
                            if dr.applied:
                                st.markdown(f"  - {dr.condition}: `{dr.penalty:+.1f}`")
                st.divider()

    st.subheader("Download")
    payload = [r.model_dump() for r in results]
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "Download JSON",
            data=json.dumps(payload, indent=2),
            file_name=f"grades_{rubric.exam_id if rubric else 'export'}.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl_col2:
        # Flat CSV: one row per criterion
        rows: list[dict] = []
        for student in results:
            for g in student.question_grades:
                for cr in g.criterion_results:
                    rows.append(
                        {
                            "student_id": student.student_id,
                            "question_id": g.question_id,
                            "criterion_id": cr.criterion_id,
                            "marks_awarded": cr.marks_awarded,
                            "justification": cr.justification,
                            "question_total": g.total_marks,
                            "question_max": g.max_marks,
                            "student_total": student.total_score,
                            "verified": g.verified,
                            "question_flags": "|".join(g.flags),
                        }
                    )
        csv_buf = io.StringIO()
        pd.DataFrame(rows).to_csv(csv_buf, index=False)
        st.download_button(
            "Download CSV",
            data=csv_buf.getvalue(),
            file_name=f"grades_{rubric.exam_id if rubric else 'export'}.csv",
            mime="text/csv",
            use_container_width=True,
        )
