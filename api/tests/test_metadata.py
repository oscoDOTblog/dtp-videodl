"""API tests for fast single-video metadata lookups."""

from __future__ import annotations

import json
import subprocess
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
            yield test_client


def _ok_payload():
    return json.dumps({"title": "Song", "uploader": "Artist", "upload_date": "20240115"})


def test_metadata_fetches_single_video_with_timeout(client):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=_ok_payload(), stderr="")

    with patch("main.subprocess.run", side_effect=fake_run):
        response = client.post(
            "/metadata",
            json={"playlist_url": "https://music.youtube.com/watch?v=abc&list=XYZ", "useCookies": False},
        )
    assert response.status_code == 200
    # A pasted playlist URL must not trigger a full playlist extraction.
    assert "--no-playlist" in captured["cmd"]
    assert captured["kwargs"].get("timeout", 0) > 0
    body = response.json()
    assert body["title"] == "Song"
    assert body["artist"] == "Artist"
    assert body["year"] == "2024"


def test_metadata_timeout_returns_504(client):
    with patch(
        "main.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=90),
    ):
        response = client.post(
            "/metadata",
            json={"playlist_url": "https://example.com/watch?v=abc", "useCookies": False},
        )
    assert response.status_code == 504


def test_metadata_yt_dlp_error_returns_400(client):
    with patch(
        "main.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["yt-dlp"], stderr="unsupported URL"),
    ):
        response = client.post(
            "/metadata",
            json={"playlist_url": "https://example.com/bad", "useCookies": False},
        )
    assert response.status_code == 400
