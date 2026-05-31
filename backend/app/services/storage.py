"""Bytes storage with pluggable backends.

Each backend resolves a logical key (e.g. ``exams/{uuid}/{pdf}.pdf``) into a
physical write/read/delete. Endpoints keep that logical key in the DB column
`exam_pdfs.file_path`; the backend handles the rest.

Backends:
- ``local`` — files under ``STORAGE_ROOT`` (default ``/data``)
- ``gcs``   — objects under ``gs://{GCS_BUCKET}/{GCS_PREFIX}/{key}``

Legacy rows that stored an absolute disk path are still readable; helpers
below detect a leading ``/`` and fall through to direct disk I/O.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


class Storage(Protocol):
    def put(self, key: str, content: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...


# ──────────────────────────────────────────────────────────────────────────
# Local filesystem
# ──────────────────────────────────────────────────────────────────────────


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, content: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        d = self._path(prefix)
        if not d.exists():
            return
        if d.is_file():
            d.unlink()
            return
        for child in sorted(d.rglob("*"), reverse=True):
            try:
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            except OSError as exc:
                log.warning("could not delete %s: %s", child, exc)
        try:
            d.rmdir()
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────────
# Google Cloud Storage
# ──────────────────────────────────────────────────────────────────────────


class GcsStorage:
    def __init__(self, bucket: str, prefix: str = "") -> None:
        from google.cloud import storage as gcs  # heavy import — deferred

        if not bucket:
            raise RuntimeError("GCS_BUCKET is not set")
        self._client = gcs.Client()
        self.bucket = self._client.bucket(bucket)
        self.prefix = prefix.strip("/")

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def put(self, key: str, content: bytes) -> str:
        full = self._full_key(key)
        blob = self.bucket.blob(full)
        blob.upload_from_string(content, content_type="application/pdf")
        return f"gs://{self.bucket.name}/{full}"

    def get(self, key: str) -> bytes:
        return self.bucket.blob(self._full_key(key)).download_as_bytes()

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(self._full_key(key)).delete()
        except NotFound:
            pass

    def delete_prefix(self, prefix: str) -> None:
        full = self._full_key(prefix)
        for blob in self._client.list_blobs(self.bucket, prefix=full):
            blob.delete()


# ──────────────────────────────────────────────────────────────────────────
# Factory + path helpers
# ──────────────────────────────────────────────────────────────────────────


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.STORAGE_BACKEND.lower() == "gcs":
        return GcsStorage(settings.GCS_BUCKET, settings.GCS_PREFIX)
    return LocalStorage(Path(settings.STORAGE_ROOT))


def pdf_key(exam_id, pdf_id) -> str:
    """The canonical logical key for a PDF row."""
    return f"exams/{exam_id}/{pdf_id}.pdf"


def read_pdf_bytes(file_path: str) -> bytes:
    """Read a PDF row's bytes. Handles both logical keys and legacy absolute paths."""
    if file_path.startswith("/"):  # legacy absolute disk path
        return Path(file_path).read_bytes()
    return get_storage().get(file_path)


def delete_pdf(file_path: str) -> None:
    if file_path.startswith("/"):
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete %s: %s", file_path, exc)
        return
    get_storage().delete(file_path)
