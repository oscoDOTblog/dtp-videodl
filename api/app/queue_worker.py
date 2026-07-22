"""Bounded background worker that leases and processes queue jobs."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app import queue_store
from app.download_service import DownloadCancelled, DownloadFailed, kill_process, run_download
from app.library_service import LibraryError, cleanup_job_dir, prepare_tracks, save_to_library
from app.paths import MAX_DOWNLOAD_WORKERS
from app.tunes_client import ScanRequestError, request_tunes_scan

logger = logging.getLogger("videodl.worker")

_stop = threading.Event()
_threads: list[threading.Thread] = []
_db_path: Optional[Path] = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_workers(db_path: Path | None = None, workers: int | None = None) -> None:
    global _db_path
    _db_path = db_path
    queue_store.init_db(db_path)
    recovered = queue_store.recover_stale_leases(db_path)
    if recovered:
        logger.info("Recovered %s in-flight queue leases", recovered)

    count = workers if workers is not None else MAX_DOWNLOAD_WORKERS
    _stop.clear()
    for index in range(count):
        thread = threading.Thread(
            target=_worker_loop,
            name=f"videodl-queue-worker-{index}",
            args=(f"worker-{index}-{os.getpid()}",),
            daemon=True,
        )
        _threads.append(thread)
        thread.start()
    logger.info("Started %s queue worker(s)", count)


def stop_workers() -> None:
    _stop.set()
    for thread in _threads:
        thread.join(timeout=2)
    _threads.clear()


def _worker_loop(owner: str) -> None:
    while not _stop.is_set():
        try:
            job = queue_store.lease_next_job(owner, db_path=_db_path)
            if not job:
                _stop.wait(1.0)
                continue
            _process_job(job, owner)
        except Exception:  # noqa: BLE001
            logger.exception("Queue worker %s crashed on a job", owner)
            _stop.wait(2.0)


def _process_job(job: dict, owner: str) -> None:
    job_id = job["id"]
    logger.info("Worker %s processing job %s (%s / %s)", owner, job_id, job["mode"], job["status"])

    if job.get("cancelRequested"):
        queue_store.mark_cancelled(job_id, db_path=_db_path)
        return

    # Scan-only retry path for albums already written to disk.
    if job["status"] == "savedScanPending":
        _request_scan(job_id)
        return

    if job["status"] == "finalizing":
        _finalize_queue_job(job, owner)
        return

    # downloading / freshly leased queued jobs
    try:
        def on_progress(payload: dict) -> None:
            queue_store.update_job(
                job_id,
                db_path=_db_path,
                current=payload.get("current", 0),
                total=payload.get("total", 0),
                currentTitle=payload.get("currentTitle"),
                status="downloading",
            )
            queue_store.renew_lease(job_id, owner, db_path=_db_path)

        tracks = run_download(
            job_id,
            job["playlistUrl"],
            use_cookies=job["useCookies"],
            on_progress=on_progress,
            should_cancel=lambda: queue_store.is_cancel_requested(job_id, db_path=_db_path),
        )
    except DownloadCancelled:
        kill_process(job_id)
        queue_store.mark_cancelled(job_id, db_path=_db_path, error="cancelled during download")
        return
    except DownloadFailed as exc:
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="failed",
            error=str(exc)[:2000],
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Download failed for %s", job_id)
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="failed",
            error=str(exc)[:2000],
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return

    if queue_store.is_cancel_requested(job_id, db_path=_db_path):
        queue_store.mark_cancelled(job_id, db_path=_db_path)
        return

    manifest = {"tracks": tracks}
    queue_store.update_job(job_id, db_path=_db_path, manifest=manifest)

    if job["mode"] == "oneOff":
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="readyForReview",
            current=len(tracks),
            total=len(tracks),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return

    # Queue mode: auto-finalize using metadata order.
    refreshed = queue_store.get_job(job_id, db_path=_db_path)
    if not refreshed:
        return
    queue_store.update_job(job_id, db_path=_db_path, status="finalizing")
    _finalize_queue_job(refreshed, owner)


def _finalize_queue_job(job: dict, owner: str) -> None:
    job_id = job["id"]
    if queue_store.is_cancel_requested(job_id, db_path=_db_path):
        queue_store.mark_cancelled(job_id, db_path=_db_path)
        return

    tracks = (job.get("manifest") or {}).get("tracks") or []
    if not tracks:
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="failed",
            error="No tracks available to finalize",
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return

    try:
        queue_store.renew_lease(job_id, owner, db_path=_db_path)
        prepared = prepare_tracks(
            job_id,
            job["album"],
            tracks,
            cover_path=job.get("coverPath"),
        )
        library_dir = save_to_library(
            job["album"].get("artist") or "",
            job["album"].get("title") or "",
            prepared,
        )
        cleanup_job_dir(job_id)
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="savedScanPending",
            libraryPath=str(library_dir),
            error=None,
        )
    except LibraryError as exc:
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="failed",
            error=str(exc)[:2000],
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Finalize failed for %s", job_id)
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="failed",
            error=str(exc)[:2000],
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
        )
        return

    _request_scan(job_id)


def _request_scan(job_id: str) -> None:
    try:
        request_tunes_scan()
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="completed",
            finishedAt=_utcnow(),
            leaseOwner=None,
            leaseExpiresAt=None,
            error=None,
        )
    except ScanRequestError as exc:
        logger.warning("Scan request pending for %s: %s", job_id, exc)
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="savedScanPending",
            error=f"Saved, waiting for scan: {exc}"[:2000],
            leaseOwner=None,
            leaseExpiresAt=None,
        )


def save_one_off_job(job_id: str, ordered_tracks: list[dict]) -> dict:
    """Tag + save a readyForReview one-off job, then request scan."""
    job = queue_store.get_job(job_id, db_path=_db_path)
    if not job:
        raise LibraryError("Job not found", status_code=404)
    if job["status"] != "readyForReview":
        raise LibraryError(f"Job is not ready for review (status={job['status']})", status_code=409)
    if job["mode"] != "oneOff":
        raise LibraryError("Only one-off jobs can be saved from review", status_code=400)

    manifest_tracks = (job.get("manifest") or {}).get("tracks") or []
    by_id = {t["id"]: t for t in manifest_tracks}
    resolved = []
    for track in ordered_tracks:
        source = by_id.get(track.get("id"))
        if not source:
            raise LibraryError(f"Unknown track id: {track.get('id')}")
        resolved.append({"id": source["id"], "path": source["path"], "title": track.get("title") or source["title"]})

    queue_store.update_job(job_id, db_path=_db_path, status="finalizing", cancelRequested=False)
    try:
        prepared = prepare_tracks(
            job_id,
            job["album"],
            resolved,
            cover_path=job.get("coverPath"),
        )
        library_dir = save_to_library(
            job["album"].get("artist") or "",
            job["album"].get("title") or "",
            prepared,
        )
        cleanup_job_dir(job_id)
        queue_store.update_job(
            job_id,
            db_path=_db_path,
            status="savedScanPending",
            libraryPath=str(library_dir),
            manifest={"tracks": resolved},
        )
    except LibraryError:
        queue_store.update_job(job_id, db_path=_db_path, status="readyForReview")
        raise

    _request_scan(job_id)
    refreshed = queue_store.get_job(job_id, db_path=_db_path)
    assert refreshed is not None
    return refreshed
