"""API tests for queue enqueue / transitions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from app import queue_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_DOWNLOAD_WORKERS", "0")
    monkeypatch.setenv("MUSIC_LIBRARY_ROOT", str(tmp_path / "music"))

    # Rebind path constants used by the store / API for this test process.
    import app.paths as paths

    paths.DATA_DIR = tmp_path
    paths.JOBS_DIR = tmp_path / "jobs"
    paths.OUT_DIR = tmp_path / "out"
    paths.QUEUE_DB_PATH = tmp_path / "queue.sqlite3"
    paths.MUSIC_LIBRARY_ROOT = tmp_path / "music"
    paths.COOKIES_DIR = tmp_path / "cookies"
    paths.COOKIES_FILE = paths.COOKIES_DIR / "cookies.txt"
    paths.COOKIES_META_FILE = paths.COOKIES_DIR / "cookies.meta.json"
    paths.ensure_dirs()
    queue_store.init_db(paths.QUEUE_DB_PATH)

    with patch("main.start_workers"):
        import main as api_main

        # Point API helpers at the temp dirs as well.
        api_main.JOBS_DIR = paths.JOBS_DIR
        api_main.OUT_DIR = paths.OUT_DIR
        with TestClient(api_main.app) as test_client:
            yield test_client, paths.QUEUE_DB_PATH


def test_enqueue_list_and_get(client):
    test_client, db = client
    response = test_client.post(
        "/queue/jobs",
        json={
            "mode": "queue",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "Album", "artist": "Artist", "year": "2026"},
        },
    )
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "queued"
    assert job["mode"] == "queue"
    assert "libraryPath" not in job

    listed = test_client.get("/queue/jobs")
    assert listed.status_code == 200
    body = listed.json()
    assert body["activeCount"] == 1
    assert body["jobs"][0]["id"] == job["id"]

    detail = test_client.get(f"/queue/jobs/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == job["id"]


def test_invalid_mode(client):
    test_client, _db = client
    response = test_client.post(
        "/queue/jobs",
        json={
            "mode": "nope",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "A", "artist": "B", "year": ""},
        },
    )
    assert response.status_code == 400


def test_save_rejects_wrong_status(client):
    test_client, db = client
    created = test_client.post(
        "/queue/jobs",
        json={
            "mode": "oneOff",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "A", "artist": "B", "year": ""},
        },
    ).json()
    response = test_client.post(
        f"/queue/jobs/{created['id']}/save",
        json={"orderedTracks": [{"id": 1, "title": "Song", "path": ""}]},
    )
    assert response.status_code in {400, 409, 500}


def test_cancel_queued(client):
    test_client, _db = client
    created = test_client.post(
        "/queue/jobs",
        json={
            "mode": "queue",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "A", "artist": "B", "year": ""},
        },
    ).json()
    response = test_client.post(f"/queue/jobs/{created['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_delete_non_terminal_rejected(client):
    test_client, _db = client
    created = test_client.post(
        "/queue/jobs",
        json={
            "mode": "queue",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "A", "artist": "B", "year": ""},
        },
    ).json()
    response = test_client.delete(f"/queue/jobs/{created['id']}")
    assert response.status_code == 409
