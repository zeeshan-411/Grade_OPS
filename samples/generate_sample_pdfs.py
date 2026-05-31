"""Generate sample exam PDFs.

One PDF per student — each page is one rubric question's answer. Pages aren't
real handwriting scans, but they are rasterised image-only pages, so Gemini
Vision handles them the same way it would handle a phone photo of an exam
booklet.

Run once after pulling the repo:
    python samples/generate_sample_pdfs.py
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz  # type: ignore

HERE = Path(__file__).parent
OUT = HERE / "pdfs"
SOURCE = HERE / "sample_students.json"


def _render_answer_page(doc: fitz.Document, title: str, body: str) -> None:
    """Append a single A4 page rendering one (student, question) answer."""
    page = doc.new_page(width=595, height=842)  # A4

    page.insert_text((50, 60), title, fontname="helv", fontsize=14)
    page.draw_line((50, 80), (545, 80))

    rect = fitz.Rect(50, 100, 545, 800)
    page.insert_textbox(
        rect,
        body if body.strip() else "[BLANK PAGE]",
        fontname="cour",  # courier reads as exam-answer prose
        fontsize=11,
        align=0,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Idempotent regeneration: wipe the output dir so old per-question files
    # from earlier runs don't linger.
    for old in OUT.glob("*.pdf"):
        old.unlink()

    data = json.loads(SOURCE.read_text())

    generated: list[str] = []
    for student in data:
        sid = student["student_id"]
        doc = fitz.open()
        for answer in student["answers"]:
            qid = answer["question_id"]
            text = answer["text"]
            _render_answer_page(doc, title=f"{sid} — {qid}", body=text)

        filename = f"{sid}.pdf"
        out = OUT / filename
        doc.save(out)
        doc.close()
        generated.append(filename)
        n_pages = len(student["answers"])
        print(f"  wrote {out}  ({n_pages} page{'s' if n_pages != 1 else ''})")

    print(f"\n{len(generated)} PDFs in {OUT}/")


if __name__ == "__main__":
    main()
