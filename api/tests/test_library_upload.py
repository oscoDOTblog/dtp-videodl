"""API tests for admin MP3 library ingest."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("httpx")
pytest.importorskip("mutagen")

from fastapi.testclient import TestClient

from app import queue_store
from app.tunes_client import ScanRequestError


def _silent_mp3_bytes(title="", artist="", album="", year="", track="1") -> bytes:
    import tempfile

    from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, TRCK
    from mutagen.mp3 import MP3

    header = bytes.fromhex("fffb9064")
    frame = header + b"\x00" * (417 - 4)
    payload = frame * 8
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        path = Path(handle.name)
        handle.write(payload)
    audio = MP3(path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    if title:
        audio.tags["TIT2"] = TIT2(encoding=3, text=title)
    if album:
        audio.tags["TALB"] = TALB(encoding=3, text=album)
    if artist:
        audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
    if year:
        audio.tags["TDRC"] = TDRC(encoding=3, text=year)
    if track:
        audio.tags["TRCK"] = TRCK(encoding=3, text=str(track))
    audio.save(v2_version=3)
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


@pytest.fixture()
def client(tmp_path, monkeypatch):
    music_root = tmp_path / "music"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MAX_DOWNLOAD_WORKERS", "0")
    monkeypatch.setenv("MUSIC_LIBRARY_ROOT", str(music_root))
    monkeypatch.setenv("DTP_TUNES_API_URL", "http://tunes.test")
    monkeypatch.setenv("DTP_TUNES_INGEST_TOKEN", "test-token")

    import app.library_service as library_service
    import app.paths as paths

    paths.DATA_DIR = tmp_path
    paths.JOBS_DIR = tmp_path / "jobs"
    paths.OUT_DIR = tmp_path / "out"
    paths.QUEUE_DB_PATH = tmp_path / "queue.sqlite3"
    paths.MUSIC_LIBRARY_ROOT = music_root
    paths.COOKIES_DIR = tmp_path / "cookies"
    paths.COOKIES_FILE = paths.COOKIES_DIR / "cookies.txt"
    paths.COOKIES_META_FILE = paths.COOKIES_DIR / "cookies.meta.json"
    paths.DTP_TUNES_API_URL = "http://tunes.test"
    paths.DTP_TUNES_INGEST_TOKEN = "test-token"
    paths.ensure_dirs()
    music_root.mkdir(parents=True, exist_ok=True)
    queue_store.init_db(paths.QUEUE_DB_PATH)

    library_service.DATA_DIR = tmp_path
    library_service.MUSIC_LIBRARY_ROOT = music_root
    library_service.JOBS_DIR = paths.JOBS_DIR
    library_service.OUT_DIR = paths.OUT_DIR
    library_service.DTP_TUNES_API_URL = "http://tunes.test"
    library_service.DTP_TUNES_INGEST_TOKEN = "test-token"

    with patch("main.start_workers"):
        import main as api_main

        api_main.JOBS_DIR = paths.JOBS_DIR
        api_main.OUT_DIR = paths.OUT_DIR
        with TestClient(api_main.app) as test_client:
            yield test_client, music_root


def test_library_status_ready(client):
    test_client, _music_root = client
    response = test_client.get("/library/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["scanConfigured"] is True
    assert "libraryPath" not in body
    assert "/music" not in str(body)


def test_upload_rejects_non_mp3(client):
    test_client, _music_root = client
    response = test_client.post(
        "/library/upload",
        data={"artist": "A", "album": "B"},
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
    )
    assert response.status_code == 400
    assert "mp3" in response.json()["detail"].lower()


def test_upload_uses_form_overrides_and_merges(client):
    test_client, music_root = client
    existing = music_root / "Override Artist" / "Override Album"
    existing.mkdir(parents=True)
    (existing / "keep-me.mp3").write_bytes(b"old")

    tagged = _silent_mp3_bytes(
        title="Tagged Title",
        artist="Tagged Artist",
        album="Tagged Album",
        year="1999",
        track="2",
    )
    with patch("main.request_tunes_scan") as scan:
        response = test_client.post(
            "/library/upload",
            data={"artist": "Override Artist", "album": "Override Album", "year": "2026"},
            files=[("files", ("01 - Tagged Title.mp3", tagged, "audio/mpeg"))],
        )
        scan.assert_called_once()

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["artist"] == "Override Artist"
    assert body["album"] == "Override Album"
    assert body["scanned"] is True
    assert (existing / "keep-me.mp3").exists()
    saved = existing / "01 - Tagged Title.mp3"
    assert saved.exists()

    from mutagen.mp3 import MP3

    audio = MP3(saved)
    assert str(audio.tags["TPE1"]) == "Override Artist"
    assert str(audio.tags["TALB"]) == "Override Album"
    assert str(audio.tags["TIT2"]) == "Tagged Title"


def test_upload_reads_id3_when_form_empty(client):
    test_client, music_root = client
    tagged = _silent_mp3_bytes(
        title="Night Drive",
        artist="Neon City",
        album="After Hours",
        year="2024",
        track="3",
    )
    with patch("main.request_tunes_scan"):
        response = test_client.post(
            "/library/upload",
            files=[("files", ("night-drive.mp3", tagged, "audio/mpeg"))],
        )
    assert response.status_code == 200
    body = response.json()
    assert body["artist"] == "Neon City"
    assert body["album"] == "After Hours"
    saved = music_root / "Neon City" / "After Hours" / "night-drive.mp3"
    assert saved.exists()


def test_upload_scan_failure_still_saves(client):
    test_client, music_root = client
    tagged = _silent_mp3_bytes(title="Song", artist="Artist", album="Album")
    with patch(
        "main.request_tunes_scan",
        side_effect=ScanRequestError("scan request unreachable"),
    ):
        response = test_client.post(
            "/library/upload",
            files=[("files", ("song.mp3", tagged, "audio/mpeg"))],
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["scanned"] is False
    assert "scan" in (body.get("scanError") or "").lower()
    assert (music_root / "Artist" / "Album" / "song.mp3").exists()


def test_upload_strips_path_from_filename(client):
    test_client, music_root = client
    tagged = _silent_mp3_bytes(title="Safe", artist="Folder", album="Album")
    with patch("main.request_tunes_scan"):
        response = test_client.post(
            "/library/upload",
            files=[("files", ("../../etc/passwd.mp3", tagged, "audio/mpeg"))],
        )
    assert response.status_code == 200
    saved = music_root / "Folder" / "Album" / "passwd.mp3"
    assert saved.exists()
    assert not (music_root / "etc").exists()
