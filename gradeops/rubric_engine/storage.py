"""Pluggable storage for raw PDFs, OCR extractions, and graded results.

Two backends:
    LocalStorage  — writes under `gradeops/storage/{exam_id}/...` on disk.
                    Always works; default when no cloud creds are configured.
    GCSStorage    — uploads to a Google Cloud Storage bucket. Activated when
                    GCS_BUCKET is set and `google-cloud-storage` can authenticate
                    (via service-account JSON pointed to by GOOGLE_APPLICATION_CREDENTIALS
                    or via Application Default Credentials).

Layout (same for both backends):
    {exam_id}/pdfs/{student_id}_{question_id}.pdf
    {exam_id}/ocr/{student_id}_{question_id}.json
    {exam_id}/grades/{student_id}.json
    {exam_id}/grades_all.json
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_ROOT = REPO_ROOT / "gradeops" / "storage"


class Storage(Protocol):
    """Minimal storage interface used by the Streamlit app."""

    backend: str
    location: str  # human-readable, shown in the UI

    def save_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def save_json(self, key: str, payload: dict | list) -> str: ...
    def exists(self, key: str) -> bool: ...
    def list_prefix(self, prefix: str) -> list[str]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Local filesystem
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class LocalStorage:
    root: Path = DEFAULT_LOCAL_ROOT
    backend: str = "local"

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        return f"local://{self.root}"

    def _path(self, key: str) -> Path:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        path.write_bytes(data)
        return str(path)

    def save_json(self, key: str, payload: dict | list) -> str:
        path = self._path(key)
        path.write_text(json.dumps(payload, indent=2, default=str))
        return str(path)

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return [str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file()]


# ─────────────────────────────────────────────────────────────────────────────
# Google Cloud Storage
# ─────────────────────────────────────────────────────────────────────────────


class GCSStorage:
    backend = "gcs"

    def __init__(self, bucket_name: str, prefix: str = "gradeops") -> None:
        # Imported lazily so the module still loads cleanly when GCS isn't configured.
        from google.cloud import storage as gcs  # type: ignore

        self._client = gcs.Client()
        self._bucket = self._client.bucket(bucket_name)
        if not self._bucket.exists():
            raise RuntimeError(
                f"GCS bucket {bucket_name!r} does not exist or service account lacks access."
            )
        self._prefix = prefix.strip("/")

    @property
    def location(self) -> str:
        return f"gs://{self._bucket.name}/{self._prefix}/"

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def save_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        blob = self._bucket.blob(self._full_key(key))
        blob.upload_from_string(data, content_type=content_type)
        return self.location + key

    def save_json(self, key: str, payload: dict | list) -> str:
        return self.save_bytes(
            key,
            json.dumps(payload, indent=2, default=str).encode("utf-8"),
            content_type="application/json",
        )

    def exists(self, key: str) -> bool:
        return self._bucket.blob(self._full_key(key)).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        full = self._full_key(prefix)
        return [b.name.removeprefix(self._prefix + "/") for b in self._client.list_blobs(self._bucket, prefix=full)]


# ─────────────────────────────────────────────────────────────────────────────
# Factory + helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_storage(prefer: str | None = None) -> Storage:
    """Pick a storage backend.

    `prefer="gcs"` forces GCS — raises if creds/bucket are missing.
    `prefer="local"` forces local.
    `prefer=None` auto-detects: GCS if `GCS_BUCKET` is set, otherwise local.
    """
    if prefer is None:
        prefer = "gcs" if os.environ.get("GCS_BUCKET") else "local"

    if prefer == "gcs":
        bucket = os.environ.get("GCS_BUCKET")
        if not bucket:
            raise RuntimeError("Set GCS_BUCKET in .env to use Google Cloud Storage.")
        return GCSStorage(bucket_name=bucket, prefix=os.environ.get("GCS_PREFIX", "gradeops"))

    return LocalStorage()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_extractions(
    storage: Storage,
    exam_id: str,
    extractions: Iterable[dict],
) -> list[str]:
    """Save the raw PDF + extracted text JSON for every successful extraction.

    Returns the list of storage keys written.
    """
    keys: list[str] = []
    for ext in extractions:
        if "error" in ext:
            continue
        sid = ext["student_id"]
        qid = ext["question_id"]
        pdf_key = f"{exam_id}/pdfs/{sid}_{qid}.pdf"
        ocr_key = f"{exam_id}/ocr/{sid}_{qid}.json"

        if "pdf_bytes" in ext and ext["pdf_bytes"]:
            storage.save_bytes(pdf_key, ext["pdf_bytes"], content_type="application/pdf")
            keys.append(pdf_key)

        ocr_record = {
            "student_id": sid,
            "question_id": qid,
            "source_file": ext.get("source_file"),
            "engine": ext.get("engine"),
            "text": ext.get("text", ""),
            "ocr_confidence": ext.get("ocr_confidence"),
            "extracted_at": _iso_now(),
        }
        storage.save_json(ocr_key, ocr_record)
        keys.append(ocr_key)

    return keys


def persist_grades(storage: Storage, exam_id: str, student_grades: list) -> list[str]:
    """Save graded results (one JSON per student plus a combined file)."""
    keys: list[str] = []
    payloads = []
    for student in student_grades:
        sid = student.student_id if hasattr(student, "student_id") else student["student_id"]
        payload = student.model_dump() if hasattr(student, "model_dump") else dict(student)
        payload["graded_at"] = _iso_now()
        per_student_key = f"{exam_id}/grades/{sid}.json"
        storage.save_json(per_student_key, payload)
        keys.append(per_student_key)
        payloads.append(payload)

    combined_key = f"{exam_id}/grades_all.json"
    storage.save_json(
        combined_key,
        {"exam_id": exam_id, "graded_at": _iso_now(), "students": payloads},
    )
    keys.append(combined_key)
    return keys
