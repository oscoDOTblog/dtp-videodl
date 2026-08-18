"""Shared path and environment helpers for VideoDL."""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
MUSIC_LIBRARY_ROOT = Path(os.environ.get("MUSIC_LIBRARY_ROOT", "/music")).resolve()
COOKIES_DIR = Path(os.environ.get("COOKIES_DIR", "/cookies")).resolve()
COOKIES_FILE = COOKIES_DIR / "youtube.cookies.txt"
COOKIES_META_FILE = COOKIES_DIR / "youtube.cookies.meta.json"
JOBS_DIR = DATA_DIR / "jobs"
OUT_DIR = DATA_DIR / "out"
QUEUE_DB_PATH = DATA_DIR / "queue.sqlite3"

MAX_DOWNLOAD_WORKERS = max(0, int(os.environ.get("MAX_DOWNLOAD_WORKERS", "1")))
LEASE_SECONDS = int(os.environ.get("QUEUE_LEASE_SECONDS", "600"))
DTP_TUNES_API_URL = os.environ.get("DTP_TUNES_API_URL", "").rstrip("/")
DTP_TUNES_INGEST_TOKEN = os.environ.get("DTP_TUNES_INGEST_TOKEN", "")
MAX_LIBRARY_UPLOAD_FILES = max(1, int(os.environ.get("MAX_LIBRARY_UPLOAD_FILES", "50")))
MAX_LIBRARY_UPLOAD_BYTES = max(1, int(os.environ.get("MAX_LIBRARY_UPLOAD_BYTES", str(200 * 1024 * 1024))))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
