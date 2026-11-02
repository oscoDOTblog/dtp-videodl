"""Zip-download endpoint: single track returns raw MP3, multi returns ZIP."""

from __future__ import annotations

import sys
import zipfile
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

        api_main.JOBS_DIR = paths.JOBS_DIR
        api_main.OUT_DIR = paths.OUT_DIR
        with TestClient(api_main.app) as test_client:
            yield test_client, paths


def _make_review_job(test_client, paths, tracks):
    created = test_client.post(
        "/queue/jobs",
        json={
            "mode": "oneOff",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "Album", "artist": "Artist", "year": "2026"},
        },
    ).json()
    queue_store.update_job(
        created["id"],
        db_path=paths.QUEUE_DB_PATH,
        status="readyForReview",
        manifest={"tracks": tracks},
    )
    return created["id"]


def test_single_track_returns_raw_mp3(client, tmp_path):
    test_client, paths = client
    job_id = _make_review_job(
        test_client,
        paths,
        [{"id": 1, "title": "Only Song", "path": "/tmp/only.mp3"}],
    )
    mp3 = tmp_path / "01 - Only Song.mp3"
    mp3.write_bytes(b"ID3fake-mp3-bytes")

    with patch("main.prepare_tracks", return_value=[mp3]):
        response = test_client.post(
            f"/queue/jobs/{job_id}/zip",
            json={"orderedTracks": [{"id": 1, "title": "Only Song", "path": ""}]},
        )
    assert response.status_code == 200
    assert "audio" in response.headers["content-type"]
    assert response.content == b"ID3fake-mp3-bytes"
    assert ".mp3" in response.headers["content-disposition"]
    assert ".zip" not in response.headers["content-disposition"]


def test_multi_track_returns_zip(client, tmp_path):
    test_client, paths = client
    job_id = _make_review_job(
        test_client,
        paths,
        [
            {"id": 1, "title": "Song One", "path": "/tmp/one.mp3"},
            {"id": 2, "title": "Song Two", "path": "/tmp/two.mp3"},
        ],
    )
    first = tmp_path / "01 - Song One.mp3"
    second = tmp_path / "02 - Song Two.mp3"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with patch("main.prepare_tracks", return_value=[first, second]):
        response = test_client.post(
            f"/queue/jobs/{job_id}/zip",
            json={
                "orderedTracks": [
                    {"id": 1, "title": "Song One", "path": ""},
                    {"id": 2, "title": "Song Two", "path": ""},
                ]
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert ".zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(__import__("io").BytesIO(response.content)) as zf:
        assert sorted(zf.namelist()) == [
            "01 - Song One.mp3",
            "02 - Song Two.mp3",
        ]


def _make_completed_job(test_client, paths, files: dict[str, bytes]):
    created = test_client.post(
        "/queue/jobs",
        json={
            "mode": "queue",
            "playlistUrl": "https://example.com/list",
            "useCookies": False,
            "album": {"title": "Album", "artist": "Artist", "year": "2026"},
        },
    ).json()
    library_dir = paths.MUSIC_LIBRARY_ROOT / "Artist" / "Album"
    library_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        (library_dir / name).write_bytes(payload)
    queue_store.update_job(
        created["id"],
        db_path=paths.QUEUE_DB_PATH,
        status="completed",
        libraryPath=str(library_dir),
    )
    return created["id"]


def test_download_serves_single_library_mp3(client):
    test_client, paths = client
    job_id = _make_completed_job(
        test_client, paths, {"01 - Only Song.mp3": b"ID3fake-mp3-bytes"}
    )
    response = test_client.get(f"/queue/jobs/{job_id}/download")
    assert response.status_code == 200
    assert "audio" in response.headers["content-type"]
    assert response.content == b"ID3fake-mp3-bytes"
    assert ".mp3" in response.headers["content-disposition"]


def test_download_serves_library_mp3s_as_zip(client):
    test_client, paths = client
    job_id = _make_completed_job(
        test_client,
        paths,
        {"01 - One.mp3": b"first", "02 - Two.mp3": b"second"},
    )
    response = test_client.get(f"/queue/jobs/{job_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(__import__("io").BytesIO(response.content)) as zf:
        assert sorted(zf.namelist()) == ["01 - One.mp3", "02 - Two.mp3"]


def test_download_missing_files_returns_404(client, tmp_path):
    test_client, paths = client
    job_id = _make_completed_job(test_client, paths, {"01 - Gone.mp3": b"x"})
    # Simulate cleanup: library dir removed after completion.
    import shutil

    shutil.rmtree(paths.MUSIC_LIBRARY_ROOT / "Artist" / "Album")
    response = test_client.get(f"/queue/jobs/{job_id}/download")
    assert response.status_code == 404
    assert "no longer on the server" in response.json()["detail"]


def test_download_unknown_job_returns_404(client):
    test_client, _paths = client
    response = test_client.get("/queue/jobs/does-not-exist/download")
    assert response.status_code == 404
