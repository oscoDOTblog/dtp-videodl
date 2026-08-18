"""SQLite-backed durable download queue."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app import paths
from app.paths import LEASE_SECONDS


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset(
    {"queued", "downloading", "finalizing", "readyForReview", "savedScanPending"}
)
CANCELABLE_STATUSES = frozenset({"queued", "downloading", "finalizing", "savedScanPending"})
RETRYABLE_STATUSES = frozenset({"failed", "cancelled"})

_lock = threading.Lock()
_initialized = False


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> Path:
    return paths.QUEUE_DB_PATH


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db(db_path: Path | None = None):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    global _initialized
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with _db(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    playlist_url TEXT NOT NULL,
                    use_cookies INTEGER NOT NULL DEFAULT 1,
                    album_title TEXT NOT NULL DEFAULT '',
                    album_artist TEXT NOT NULL DEFAULT '',
                    album_year TEXT NOT NULL DEFAULT '',
                    cover_path TEXT,
                    current INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0,
                    current_title TEXT,
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    library_path TEXT,
                    manifest_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC)")
        _initialized = True


def _row_to_job(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["useCookies"] = bool(data.pop("use_cookies"))
    data["cancelRequested"] = bool(data.pop("cancel_requested"))
    data["playlistUrl"] = data.pop("playlist_url")
    data["album"] = {
        "title": data.pop("album_title") or "",
        "artist": data.pop("album_artist") or "",
        "year": data.pop("album_year") or "",
    }
    data["coverPath"] = data.pop("cover_path")
    data["currentTitle"] = data.pop("current_title")
    data["retryCount"] = data.pop("retry_count")
    data["leaseOwner"] = data.pop("lease_owner")
    data["leaseExpiresAt"] = data.pop("lease_expires_at")
    data["libraryPath"] = data.pop("library_path")
    data["createdAt"] = data.pop("created_at")
    data["updatedAt"] = data.pop("updated_at")
    data["startedAt"] = data.pop("started_at")
    data["finishedAt"] = data.pop("finished_at")
    manifest_json = data.pop("manifest_json")
    data["manifest"] = json.loads(manifest_json) if manifest_json else None
    return data


def create_job(
    *,
    mode: str,
    playlist_url: str,
    use_cookies: bool,
    album: dict[str, str],
    cover_path: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    init_db(db_path)
    job_id = uuid.uuid4().hex
    now = _utcnow()
    with _lock:
        with _db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, mode, status, playlist_url, use_cookies,
                    album_title, album_artist, album_year, cover_path,
                    created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    mode,
                    playlist_url,
                    1 if use_cookies else 0,
                    album.get("title") or "",
                    album.get("artist") or "",
                    album.get("year") or "",
                    cover_path,
                    now,
                    now,
                ),
            )
    return get_job(job_id, db_path=db_path)  # type: ignore[return-value]


def get_job(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    init_db(db_path)
    with _db(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def list_jobs(db_path: Path | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    init_db(db_path)
    with _db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(r) for r in rows if r]  # type: ignore[misc]


def count_active(db_path: Path | None = None) -> int:
    init_db(db_path)
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with _db(db_path) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM jobs WHERE status IN ({placeholders})",
            tuple(ACTIVE_STATUSES),
        ).fetchone()
    return int(row["c"] if row else 0)


def update_job(job_id: str, db_path: Path | None = None, **fields: Any) -> dict[str, Any] | None:
    init_db(db_path)
    column_map = {
        "status": "status",
        "current": "current",
        "total": "total",
        "currentTitle": "current_title",
        "error": "error",
        "retryCount": "retry_count",
        "leaseOwner": "lease_owner",
        "leaseExpiresAt": "lease_expires_at",
        "cancelRequested": "cancel_requested",
        "libraryPath": "library_path",
        "coverPath": "cover_path",
        "manifest": "manifest_json",
        "startedAt": "started_at",
        "finishedAt": "finished_at",
    }
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        col = column_map.get(key)
        if not col:
            continue
        if key == "manifest":
            value = json.dumps(value) if value is not None else None
        if key == "cancelRequested":
            value = 1 if value else 0
        assignments.append(f"{col} = ?")
        values.append(value)
    if not assignments:
        return get_job(job_id, db_path=db_path)
    assignments.append("updated_at = ?")
    values.append(_utcnow())
    values.append(job_id)
    with _lock:
        with _db(db_path) as conn:
            conn.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
    return get_job(job_id, db_path=db_path)


def lease_next_job(owner: str, db_path: Path | None = None, *, lease_seconds: int | None = None) -> dict[str, Any] | None:
    """Atomically lease the oldest queued job for downloading/finalizing."""
    init_db(db_path)
    seconds = lease_seconds if lease_seconds is not None else LEASE_SECONDS
    now = datetime.now(timezone.utc)
    expires = datetime.fromtimestamp(now.timestamp() + seconds, timezone.utc).isoformat()
    now_iso = now.isoformat()
    with _lock:
        with _db(db_path) as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                   OR (
                        status IN ('downloading', 'finalizing', 'savedScanPending')
                        AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                        AND cancel_requested = 0
                   )
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now_iso,),
            ).fetchone()
            if not row:
                return None
            job_id = row["id"]
            status = row["status"]
            next_status = "downloading" if status in {"queued", "downloading"} else status
            if status == "savedScanPending":
                next_status = "savedScanPending"
            elif status == "finalizing":
                next_status = "finalizing"
            elif row["mode"] == "queue" and status == "queued":
                next_status = "downloading"
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, lease_owner = ?, lease_expires_at = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (next_status, owner, expires, now_iso, now_iso, job_id),
            )
            refreshed = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(refreshed)


def renew_lease(job_id: str, owner: str, db_path: Path | None = None, *, lease_seconds: int | None = None) -> bool:
    init_db(db_path)
    seconds = lease_seconds if lease_seconds is not None else LEASE_SECONDS
    expires = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + seconds, timezone.utc
    ).isoformat()
    with _lock:
        with _db(db_path) as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND cancel_requested = 0
                """,
                (expires, _utcnow(), job_id, owner),
            )
            return cur.rowcount > 0


def request_cancel(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    job = get_job(job_id, db_path=db_path)
    if not job:
        return None
    if job["status"] not in CANCELABLE_STATUSES and job["status"] != "readyForReview":
        return job
    if job["status"] in {"queued", "readyForReview"}:
        return update_job(
            job_id,
            db_path=db_path,
            status="cancelled",
            cancelRequested=True,
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
    return update_job(job_id, db_path=db_path, cancelRequested=True)


def mark_cancelled(job_id: str, db_path: Path | None = None, error: str | None = None) -> dict[str, Any] | None:
    return update_job(
        job_id,
        db_path=db_path,
        status="cancelled",
        cancelRequested=True,
        error=error,
        finishedAt=_utcnow(),
        leaseOwner=None,
        leaseExpiresAt=None,
    )


def retry_job(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    job = get_job(job_id, db_path=db_path)
    if not job or job["status"] not in RETRYABLE_STATUSES:
        return job
    return update_job(
        job_id,
        db_path=db_path,
        status="queued",
        cancelRequested=False,
        error=None,
        current=0,
        total=0,
        currentTitle=None,
        retryCount=job["retryCount"] + 1,
        finishedAt=None,
        leaseOwner=None,
        leaseExpiresAt=None,
        libraryPath=None,
        # Keep manifest for one-off review retries that already downloaded.
        # Failed downloads should clear it; caller decides via clear_manifest.
    )


def delete_job(job_id: str, db_path: Path | None = None) -> bool:
    job = get_job(job_id, db_path=db_path)
    if not job or job["status"] not in TERMINAL_STATUSES:
        return False
    with _lock:
        with _db(db_path) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return True


def clear_terminal(db_path: Path | None = None) -> int:
    init_db(db_path)
    placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
    with _lock:
        with _db(db_path) as conn:
            cur = conn.execute(
                f"DELETE FROM jobs WHERE status IN ({placeholders})",
                tuple(TERMINAL_STATUSES),
            )
            return cur.rowcount


def clear_all(db_path: Path | None = None) -> list[str]:
    """Delete every job. Returns removed ids so callers can clean job dirs."""
    init_db(db_path)
    with _lock:
        with _db(db_path) as conn:
            rows = conn.execute("SELECT id FROM jobs").fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                conn.execute("DELETE FROM jobs")
            return ids


def recover_stale_leases(db_path: Path | None = None) -> int:
    """On startup, put in-flight jobs back into queued (or keep savedScanPending)."""
    init_db(db_path)
    now = _utcnow()
    with _lock:
        with _db(db_path) as conn:
            cur = conn.execute(
                """
                UPDATE jobs
                SET status = CASE
                        WHEN status = 'savedScanPending' THEN 'savedScanPending'
                        ELSE 'queued'
                    END,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE status IN ('downloading', 'finalizing', 'savedScanPending')
                """,
                (now,),
            )
            return cur.rowcount


def is_cancel_requested(job_id: str, db_path: Path | None = None) -> bool:
    job = get_job(job_id, db_path=db_path)
    # Missing jobs (cleared from the queue) should stop in-flight workers.
    return job is None or bool(job.get("cancelRequested"))


def public_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip internal filesystem fields for API responses."""
    if not job:
        return None
    out = {
        "id": job["id"],
        "mode": job["mode"],
        "status": job["status"],
        "playlistUrl": job["playlistUrl"],
        "useCookies": job["useCookies"],
        "album": job["album"],
        "current": job["current"],
        "total": job["total"],
        "currentTitle": job["currentTitle"],
        "error": job["error"],
        "retryCount": job["retryCount"],
        "cancelRequested": job["cancelRequested"],
        "createdAt": job["createdAt"],
        "updatedAt": job["updatedAt"],
        "startedAt": job["startedAt"],
        "finishedAt": job["finishedAt"],
        "hasCover": bool(job.get("coverPath")),
        "hasLibraryPath": bool(job.get("libraryPath")),
    }
    if job.get("manifest"):
        # Only expose track id/title, not absolute paths, until save time needs them server-side.
        tracks = []
        for t in job["manifest"].get("tracks") or []:
            tracks.append({"id": t.get("id"), "title": t.get("title")})
        out["tracks"] = tracks
    else:
        out["tracks"] = None
    return out
