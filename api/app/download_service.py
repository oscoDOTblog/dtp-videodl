"""yt-dlp download helpers with progress callbacks and cancellation."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from app.paths import COOKIES_FILE, JOBS_DIR

logger = logging.getLogger("videodl.download")

ProgressCallback = Callable[[dict], None]
CancelCheck = Callable[[], bool]


class DownloadCancelled(Exception):
    """Raised when a job cancel is requested mid-download."""


class DownloadFailed(Exception):
    """Raised when yt-dlp exits non-zero."""


_active_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


def build_yt_dlp_cmd(base_cmd: list[str], use_cookies: bool = True) -> list[str]:
    cmd = list(base_cmd)
    if use_cookies and COOKIES_FILE.exists():
        cmd.extend(["--cookies", str(COOKIES_FILE)])
    return cmd


def register_process(job_id: str, process: subprocess.Popen) -> None:
    with _process_lock:
        _active_processes[job_id] = process


def unregister_process(job_id: str) -> None:
    with _process_lock:
        _active_processes.pop(job_id, None)


def kill_process(job_id: str) -> bool:
    with _process_lock:
        process = _active_processes.get(job_id)
    if not process or process.poll() is not None:
        return False
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return True
    except OSError as exc:
        logger.warning("Failed to kill yt-dlp for %s: %s", job_id, exc)
        return False


def build_track_manifest(job_id: str) -> list[dict]:
    job_dir = JOBS_DIR / job_id
    mp3s = sorted(p for p in job_dir.glob("*.mp3"))
    tracks = []
    for i, path in enumerate(mp3s, start=1):
        title = path.stem
        title = re.sub(r"^(?:\d+|NA)\s*-\s*", "", title, flags=re.IGNORECASE)
        title = re.sub(r"^\s*-\s*", "", title)
        tracks.append({"id": i, "path": str(path), "title": title})
    return tracks


def run_download(
    job_id: str,
    playlist_url: str,
    *,
    use_cookies: bool = True,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> list[dict]:
    """Download audio for a job. Returns track manifest. Raises on cancel/failure."""
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    template = str(job_dir / "%(playlist_index)02d - %(title)s.%(ext)s")

    def emit(payload: dict) -> None:
        if on_progress:
            on_progress(payload)

    emit({"current": 0, "total": 1, "status": "downloading", "currentTitle": None})

    try:
        _run_yt_dlp(
            job_id,
            playlist_url,
            template,
            use_cookies=use_cookies,
            on_progress=emit,
            should_cancel=should_cancel,
        )
    except DownloadFailed:
        if use_cookies:
            logger.warning("Retrying job %s without cookies", job_id)
            emit({"current": 0, "total": 1, "status": "downloading", "currentTitle": None})
            _run_yt_dlp(
                job_id,
                playlist_url,
                template,
                use_cookies=False,
                on_progress=emit,
                should_cancel=should_cancel,
            )
        else:
            raise

    tracks = build_track_manifest(job_id)
    emit(
        {
            "current": len(tracks) or 1,
            "total": len(tracks) or 1,
            "status": "downloading",
            "currentTitle": None,
        }
    )
    return tracks


def _run_yt_dlp(
    job_id: str,
    playlist_url: str,
    template: str,
    *,
    use_cookies: bool,
    on_progress: ProgressCallback,
    should_cancel: Optional[CancelCheck],
) -> None:
    cmd = build_yt_dlp_cmd(
        [
            "yt-dlp",
            playlist_url,
            "-f",
            "bestaudio/best",
            "-o",
            template,
            "--yes-playlist",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--ffmpeg-location",
            "/usr/bin/ffmpeg",
            "--progress",
        ],
        use_cookies=use_cookies,
    )

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    register_process(job_id, process)

    state = {"current": 0, "total": 1, "currentTitle": None}
    output_lines: list[str] = []

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if should_cancel and should_cancel():
                kill_process(job_id)
                raise DownloadCancelled("cancelled by user")

            line = line.strip()
            if not line:
                continue
            output_lines.append(line)

            playlist_info_match = re.search(
                r"\[.*?\]\s+Playlist.*?(\d+)\s+videos?", line, re.IGNORECASE
            )
            if playlist_info_match:
                state["total"] = int(playlist_info_match.group(1))
                on_progress({**state, "status": "downloading"})

            download_match = re.search(
                r"\[download\]\s+Downloading\s+video\s+(\d+)\s+of\s+(\d+)",
                line,
                re.IGNORECASE,
            )
            if download_match:
                state["current"] = int(download_match.group(1))
                state["total"] = int(download_match.group(2))
                on_progress({**state, "status": "downloading"})

            item_match = re.search(
                r"\[download\]\s+Downloading\s+item\s+(\d+)\s+of\s+(\d+)",
                line,
                re.IGNORECASE,
            )
            if item_match:
                state["current"] = int(item_match.group(1))
                state["total"] = int(item_match.group(2))
                on_progress({**state, "status": "downloading"})

            for pattern in (
                r"\[download\]\s+Destination:\s+.+?-\s+(.+?)\.mp3",
                r"\[download\]\s+(.+?)\s+has already been downloaded",
                r"\[ExtractAudio\]\s+Destination:\s+.+?-\s+(.+?)\.mp3",
            ):
                title_match = re.search(pattern, line)
                if title_match:
                    state["currentTitle"] = title_match.group(1).strip()
                    on_progress({**state, "status": "downloading"})
                    break

            if "[download] 100%" in line or "[ExtractAudio]" in line:
                if state["total"] == 1 and state["current"] == 0:
                    state["current"] = 1
                elif state["total"] > 1 and state["current"] < state["total"]:
                    state["current"] += 1
                on_progress({**state, "status": "downloading"})

        process.wait()
        if should_cancel and should_cancel():
            raise DownloadCancelled("cancelled by user")
        if process.returncode != 0:
            combined = "\n".join(output_lines)
            if use_cookies and "Requested format is not available" in combined:
                raise DownloadFailed(combined or "format unavailable")
            raise DownloadFailed(combined[-2000:] if combined else f"yt-dlp exit {process.returncode}")
    finally:
        unregister_process(job_id)
