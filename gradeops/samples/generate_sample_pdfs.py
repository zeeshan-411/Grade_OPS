"""Generate the sample exam PDFs that the Streamlit PDF-upload demo uses.

Each PDF mimics a single student's answer to a single rubric question. They aren't
real handwriting scans, but they ARE rasterized image-only pages — Gemini Vision
handles them the same way it would handle a phone-photo of an exam booklet.

Run once after pulling the repo:
    /Users/zeeshan/Library/Caches/gradeops-venv/bin/python gradeops/samples/generate_sample_pdfs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz  # type: ignore

HERE = Path(__file__).parent
OUT = HERE / "pdfs"
SOURCE = HERE / "sample_students.json"


def render_text_to_pdf(text: str, title: str, out_path: Path) -> None:
    """Write `text` to a single-page PDF that looks like a typed/lined exam sheet."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Header
    page.insert_text(
        (50, 60),
        title,
        fontname="helv",
        fontsize=14,
    )
    page.draw_line((50, 80), (545, 80))

    # Body — wrap roughly at 90 chars/line
    body_text = text if text.strip() else "[BLANK PAGE]"
    rect = fitz.Rect(50, 100, 545, 800)
    page.insert_textbox(
        rect,
        body_text,
        fontname="cour",  # courier — looks more like an exam answer
        fontsize=11,
        align=0,
    )

    doc.save(out_path)
    doc.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(SOURCE.read_text())

    generated = []
    for student in data:
        sid = student["student_id"]
        for answer in student["answers"]:
            qid = answer["question_id"]
            text = answer["text"]
            filename = f"{sid}_{qid}.pdf"
            out = OUT / filename
            title = f"{sid} — {qid}"
            render_text_to_pdf(text, title, out)
            generated.append(filename)
            print(f"  wrote {out}")

    print(f"\n{len(generated)} PDFs in {OUT}/")


if __name__ == "__main__":
    main()
