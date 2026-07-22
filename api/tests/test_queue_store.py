"""Unit tests for durable SQLite queue store."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import queue_store


def test_create_list_and_lease(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="queue",
        playlist_url="https://example.com/x",
        use_cookies=False,
        album={"title": "T", "artist": "A", "year": "2026"},
        db_path=db,
    )
    assert job["status"] == "queued"
    assert queue_store.count_active(db_path=db) == 1

    leased = queue_store.lease_next_job("worker-1", db_path=db)
    assert leased is not None
    assert leased["id"] == job["id"]
    assert leased["status"] == "downloading"
    assert leased["leaseOwner"] == "worker-1"

    # No second job available
    assert queue_store.lease_next_job("worker-2", db_path=db) is None


def test_cancel_queued(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="oneOff",
        playlist_url="https://example.com/x",
        use_cookies=True,
        album={"title": "T", "artist": "A", "year": ""},
        db_path=db,
    )
    updated = queue_store.request_cancel(job["id"], db_path=db)
    assert updated["status"] == "cancelled"
    assert updated["cancelRequested"] is True


def test_retry_failed(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="queue",
        playlist_url="https://example.com/x",
        use_cookies=False,
        album={"title": "T", "artist": "A", "year": ""},
        db_path=db,
    )
    queue_store.update_job(job["id"], db_path=db, status="failed", error="boom")
    retried = queue_store.retry_job(job["id"], db_path=db)
    assert retried["status"] == "queued"
    assert retried["retryCount"] == 1
    assert retried["error"] is None


def test_recover_stale_leases(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="queue",
        playlist_url="https://example.com/x",
        use_cookies=False,
        album={"title": "T", "artist": "A", "year": ""},
        db_path=db,
    )
    queue_store.update_job(
        job["id"],
        db_path=db,
        status="downloading",
        leaseOwner="dead-worker",
        leaseExpiresAt="2000-01-01T00:00:00+00:00",
    )
    recovered = queue_store.recover_stale_leases(db_path=db)
    assert recovered >= 1
    refreshed = queue_store.get_job(job["id"], db_path=db)
    assert refreshed["status"] == "queued"
    assert refreshed["leaseOwner"] is None


def test_public_job_hides_paths(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="oneOff",
        playlist_url="https://example.com/x",
        use_cookies=False,
        album={"title": "T", "artist": "A", "year": ""},
        db_path=db,
    )
    queue_store.update_job(
        job["id"],
        db_path=db,
        status="readyForReview",
        manifest={"tracks": [{"id": 1, "path": "/secret/a.mp3", "title": "Song"}]},
        coverPath="/secret/cover.jpg",
    )
    public = queue_store.public_job(queue_store.get_job(job["id"], db_path=db))
    assert public["tracks"][0]["title"] == "Song"
    assert "path" not in public["tracks"][0]
    assert "coverPath" not in public
    assert public["hasCover"] is True


def test_delete_only_terminal(tmp_path):
    db = tmp_path / "queue.sqlite3"
    job = queue_store.create_job(
        mode="queue",
        playlist_url="https://example.com/x",
        use_cookies=False,
        album={"title": "T", "artist": "A", "year": ""},
        db_path=db,
    )
    assert queue_store.delete_job(job["id"], db_path=db) is False
    queue_store.update_job(job["id"], db_path=db, status="completed")
    assert queue_store.delete_job(job["id"], db_path=db) is True
    assert queue_store.get_job(job["id"], db_path=db) is None
