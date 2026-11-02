"""VideoDL FastAPI entrypoint: metadata, legacy download APIs, and durable queue."""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import queue_store
from app.download_service import build_yt_dlp_cmd, kill_process
from app.library_service import (
    ALLOWED_COVER_TYPES,
    LibraryError,
    cleanup_job_dir,
    create_zip,
    ingest_uploaded_mp3s,
    library_mount_status,
    prepare_tracks,
    save_cover_bytes,
    save_to_library,
)
from app.paths import (
    COOKIES_DIR,
    COOKIES_FILE,
    COOKIES_META_FILE,
    JOBS_DIR,
    MAX_LIBRARY_UPLOAD_BYTES,
    MAX_LIBRARY_UPLOAD_FILES,
    OUT_DIR,
    ensure_dirs,
)
from app.tunes_client import ScanRequestError, request_tunes_scan
from app.queue_worker import save_one_off_job, start_workers
from app.sanitize import sanitize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("videodl.api")

ensure_dirs()
queue_store.init_db()


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_workers()
    yield


app = FastAPI(title="VideoDL API", lifespan=lifespan)

cors_origins_env = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:8546")
cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AlbumMeta(BaseModel):
    title: str = Field(default="")
    artist: str = Field(default="")
    year: str = Field(default="")


class TrackIn(BaseModel):
    id: int
    path: str = ""
    title: str


class DownloadReq(BaseModel):
    playlist_url: str
    album: AlbumMeta
    useCookies: bool = True


class MetadataReq(BaseModel):
    playlist_url: str
    useCookies: bool = True


class MetadataResp(BaseModel):
    title: str = Field(default="")
    artist: str = Field(default="")
    year: str = Field(default="")
    cover_base64: Optional[str] = None


class DownloadResp(BaseModel):
    job_id: str
    out_dir: str
    tracks: List[TrackIn]


class FinalizeReq(BaseModel):
    job_id: str
    album: AlbumMeta
    ordered_tracks: List[TrackIn]
    cover_base64: Optional[str] = None


class FinalizeResp(BaseModel):
    ok: bool
    zip_url: str
    count: int


class LibraryFinalizeResp(BaseModel):
    ok: bool
    library_path: str
    count: int


class LibraryStatusResp(BaseModel):
    ready: bool
    scanConfigured: bool


class LibraryUploadResp(BaseModel):
    ok: bool
    count: int
    artist: str
    album: str
    scanned: bool
    scanError: Optional[str] = None


class ProgressResp(BaseModel):
    job_id: str
    current: int
    total: int
    status: str
    current_title: Optional[str] = None


class CookiesStatusResp(BaseModel):
    hasCookies: bool
    uploadedAt: Optional[str] = None


class QueueEnqueueReq(BaseModel):
    mode: str  # oneOff | queue
    playlistUrl: str
    useCookies: bool = True
    album: AlbumMeta = Field(default_factory=AlbumMeta)
    coverBase64: Optional[str] = None


class QueueSaveReq(BaseModel):
    orderedTracks: List[TrackIn]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fetch_cover_base64(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    headers = {"User-Agent": "Mozilla/5.0 VideoDL/1.0"}
    req = urllib_request.Request(url, headers=headers)
    try:
        with urllib_request.urlopen(req, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                return None
            return base64.b64encode(response.read()).decode("utf-8")
    except (URLError, HTTPError, TimeoutError, ValueError) as e:
        logger.warning("Could not fetch thumbnail for metadata prefill: %s", e)
        return None


def looks_like_netscape_cookies(content: str) -> bool:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return False
    if lines[0].startswith("# Netscape HTTP Cookie File"):
        return True
    for line in lines:
        if line.startswith("#"):
            continue
        if len(line.split("\t")) >= 7:
            return True
    return False


def get_cookies_uploaded_at() -> Optional[str]:
    if COOKIES_META_FILE.exists():
        try:
            payload = json.loads(COOKIES_META_FILE.read_text(encoding="utf-8"))
            uploaded_at = payload.get("uploadedAt")
            if isinstance(uploaded_at, str) and uploaded_at:
                return uploaded_at
        except (json.JSONDecodeError, OSError):
            pass
    if COOKIES_FILE.exists():
        try:
            modified = datetime.fromtimestamp(COOKIES_FILE.stat().st_mtime, timezone.utc)
            return modified.isoformat()
        except OSError:
            return None
    return None


def _library_http(exc: LibraryError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"file too large: {upload.filename or 'upload'}")
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Cookies / metadata (unchanged behavior)
# ---------------------------------------------------------------------------


@app.get("/cookies/status", response_model=CookiesStatusResp)
def cookies_status():
    return CookiesStatusResp(hasCookies=COOKIES_FILE.exists(), uploadedAt=get_cookies_uploaded_at())


@app.post("/cookies/upload", response_model=CookiesStatusResp)
async def upload_cookies(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="cookies file name is required")
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="cookies file is empty")
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1")
    if not looks_like_netscape_cookies(content):
        raise HTTPException(status_code=400, detail="invalid cookies file format")
    try:
        COOKIES_DIR.mkdir(parents=True, exist_ok=True)
        COOKIES_FILE.write_text(content, encoding="utf-8")
        uploaded_at = datetime.now(timezone.utc).isoformat()
        COOKIES_META_FILE.write_text(
            json.dumps({"uploadedAt": uploaded_at}, ensure_ascii=True),
            encoding="utf-8",
        )
    except OSError as e:
        logger.error("Failed saving cookies file: %s", e)
        raise HTTPException(status_code=500, detail="failed to persist cookies file")
    return CookiesStatusResp(hasCookies=True, uploadedAt=uploaded_at)


@app.get("/library/status", response_model=LibraryStatusResp)
def library_status():
    return LibraryStatusResp(**library_mount_status())


@app.post("/library/upload", response_model=LibraryUploadResp)
async def library_upload(
    files: List[UploadFile] = File(...),
    artist: str = Form(""),
    album: str = Form(""),
    year: str = Form(""),
    cover: Optional[UploadFile] = File(None),
):
    if not files:
        raise HTTPException(status_code=400, detail="at least one mp3 is required")
    if len(files) > MAX_LIBRARY_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"too many files (max {MAX_LIBRARY_UPLOAD_FILES})",
        )

    uploads: list[tuple[str, bytes]] = []
    for upload in files:
        filename = Path(upload.filename or "").name
        payload = await _read_upload_limited(upload, MAX_LIBRARY_UPLOAD_BYTES)
        uploads.append((filename, payload))

    cover_bytes = None
    cover_mime = "image/jpeg"
    if cover is not None and cover.filename:
        cover_mime = (cover.content_type or "").lower() or "image/jpeg"
        if cover_mime not in ALLOWED_COVER_TYPES:
            raise HTTPException(status_code=400, detail="cover must be a jpeg or png image")
        cover_bytes = await _read_upload_limited(cover, 8 * 1024 * 1024)
        if not cover_bytes:
            raise HTTPException(status_code=400, detail="cover image is empty")

    try:
        result = ingest_uploaded_mp3s(
            uploads,
            artist=artist or "",
            album=album or "",
            year=year or "",
            cover_bytes=cover_bytes,
            cover_mime=cover_mime,
        )
    except LibraryError as exc:
        raise _library_http(exc) from exc

    scanned = False
    scan_error = None
    try:
        request_tunes_scan()
        scanned = True
    except ScanRequestError as exc:
        logger.warning("Library upload saved but scan failed: %s", exc)
        scan_error = str(exc)

    return LibraryUploadResp(
        ok=True,
        count=result["count"],
        artist=result["artist"],
        album=result["album"],
        scanned=scanned,
        scanError=scan_error,
    )


@app.post("/metadata", response_model=MetadataResp)
def metadata(req: MetadataReq):
    # --no-playlist keeps pasted playlist URLs fast: prefill uses the single
    # video instead of extracting the whole playlist (which timed out).
    cmd = build_yt_dlp_cmd(
        [
            "yt-dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            "--no-warnings",
            req.playlist_url,
        ],
        use_cookies=req.useCookies,
    )
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=90)
    except subprocess.TimeoutExpired:
        logger.warning("Metadata lookup timed out for %s", req.playlist_url)
        raise HTTPException(
            status_code=504,
            detail="Metadata lookup timed out. Try again, or paste a single-video URL.",
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "Failed to fetch metadata").strip()
        raise HTTPException(status_code=400, detail=detail)

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Invalid metadata response from yt-dlp")

    title = (payload.get("title") or payload.get("playlist_title") or "").strip()
    artist = (
        payload.get("uploader") or payload.get("channel") or payload.get("creator") or ""
    ).strip()

    year_value = payload.get("release_year")
    if year_value:
        year = str(year_value)
    else:
        upload_date = str(payload.get("upload_date") or "")
        year = upload_date[:4] if len(upload_date) >= 4 and upload_date[:4].isdigit() else ""

    thumbnail_url = payload.get("thumbnail")
    if not thumbnail_url:
        thumbnails = payload.get("thumbnails") or []
        if thumbnails and isinstance(thumbnails, list):
            thumbnail_url = thumbnails[-1].get("url")

    return MetadataResp(
        title=title,
        artist=artist,
        year=year,
        cover_base64=fetch_cover_base64(thumbnail_url),
    )


# ---------------------------------------------------------------------------
# Durable queue API
# ---------------------------------------------------------------------------


@app.post("/queue/jobs")
def enqueue_job(req: QueueEnqueueReq):
    if req.mode not in {"oneOff", "queue"}:
        raise HTTPException(status_code=400, detail="mode must be oneOff or queue")
    if not req.playlistUrl.strip():
        raise HTTPException(status_code=400, detail="playlistUrl is required")

    job = queue_store.create_job(
        mode=req.mode,
        playlist_url=req.playlistUrl.strip(),
        use_cookies=req.useCookies,
        album=req.album.model_dump(),
    )
    assert job is not None
    JOBS_DIR.joinpath(job["id"]).mkdir(parents=True, exist_ok=True)

    if req.coverBase64:
        try:
            cover_path = save_cover_bytes(job["id"], req.coverBase64)
            queue_store.update_job(job["id"], coverPath=str(cover_path))
            job = queue_store.get_job(job["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to store cover for %s: %s", job["id"], exc)

    return queue_store.public_job(job)


@app.get("/queue/jobs")
def list_queue_jobs():
    jobs = [queue_store.public_job(j) for j in queue_store.list_jobs()]
    return {"jobs": jobs, "activeCount": queue_store.count_active()}


@app.get("/queue/jobs/{job_id}")
def get_queue_job(job_id: str):
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return queue_store.public_job(job)


@app.post("/queue/jobs/{job_id}/save")
def save_queue_job(job_id: str, req: QueueSaveReq):
    try:
        job = save_one_off_job(
            job_id,
            [{"id": t.id, "title": t.title, "path": t.path} for t in req.orderedTracks],
        )
    except LibraryError as exc:
        raise _library_http(exc) from exc
    return {
        "ok": True,
        "job": queue_store.public_job(job),
        "count": len(req.orderedTracks),
    }


@app.post("/queue/jobs/{job_id}/zip")
def zip_queue_job(job_id: str, req: QueueSaveReq):
    """Tag + zip a readyForReview one-off job for browser download.

    Leaves the job in readyForReview with an updated manifest so a later
    save still resolves the renamed files. Does not touch the library.
    """
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "readyForReview":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not ready for review (status={job['status']})",
        )
    if job["mode"] != "oneOff":
        raise HTTPException(
            status_code=400, detail="Only one-off jobs can be downloaded from review"
        )

    manifest_tracks = (job.get("manifest") or {}).get("tracks") or []
    by_id = {t["id"]: t for t in manifest_tracks}
    resolved = []
    for track in req.orderedTracks:
        source = by_id.get(track.id)
        if not source:
            raise HTTPException(status_code=400, detail=f"Unknown track id: {track.id}")
        resolved.append(
            {
                "id": source["id"],
                "path": source["path"],
                "title": track.title or source["title"],
            }
        )

    try:
        tracks = prepare_tracks(
            job_id,
            job["album"],
            resolved,
            cover_path=job.get("coverPath"),
        )
    except LibraryError as exc:
        raise _library_http(exc) from exc
    queue_store.update_job(job_id, manifest={"tracks": resolved})

    album_title = sanitize((job["album"] or {}).get("title") or "album")
    album_artist = sanitize((job["album"] or {}).get("artist") or "")
    return _serve_files_as_download(tracks, album_artist, album_title)
    zip_path = create_zip(album_artist, album_title, tracks)
    download_name = (
        f"{album_artist} - {album_title}.zip" if album_artist else f"{album_title}.zip"
    )
    return FileResponse(
        path=zip_path, filename=download_name, media_type="application/zip"
    )


def _serve_files_as_download(tracks: list[Path], album_artist: str, album_title: str):
    """Serve tagged MP3s: a single track as raw audio, several as a zip."""
    if len(tracks) == 1:
        return FileResponse(
            path=tracks[0], filename=tracks[0].name, media_type="audio/mpeg"
        )
    zip_path = create_zip(album_artist, album_title, tracks)
    download_name = (
        f"{album_artist} - {album_title}.zip" if album_artist else f"{album_title}.zip"
    )
    return FileResponse(
        path=zip_path, filename=download_name, media_type="application/zip"
    )


@app.get("/queue/jobs/{job_id}/download")
def download_queue_files(job_id: str):
    """Download a job's audio files while they are still on the server.

    Completed jobs serve from the library; jobs awaiting review serve their
    downloaded files. Single file returns raw MP3, several return a zip.
    Returns 404 when the files are gone (e.g. job cleaned up).
    """
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    files: list[Path] = []
    library_path = job.get("libraryPath")
    if library_path:
        library_dir = Path(library_path)
        if library_dir.is_dir():
            files = sorted(
                p
                for p in library_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".mp3"
            )

    if not files and job["status"] == "readyForReview":
        for track in (job.get("manifest") or {}).get("tracks") or []:
            candidate = Path(track.get("path") or "")
            if candidate.is_file():
                files.append(candidate)

    if not files:
        raise HTTPException(
            status_code=404, detail="Files are no longer on the server"
        )

    album = job.get("album") or {}
    return _serve_files_as_download(
        files,
        sanitize(album.get("artist") or ""),
        sanitize(album.get("title") or "album"),
    )


@app.post("/queue/jobs/{job_id}/cancel")
def cancel_queue_job(job_id: str):
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in queue_store.TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Job is already finished")
    kill_process(job_id)
    updated = queue_store.request_cancel(job_id)
    if updated and updated["status"] == "downloading":
        # Worker will observe cancelRequested; also mark cancelled promptly for UX.
        updated = queue_store.mark_cancelled(job_id, error="cancelled by user")
    return queue_store.public_job(updated)


@app.post("/queue/jobs/{job_id}/retry")
def retry_queue_job(job_id: str):
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in queue_store.RETRYABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Job cannot be retried")
    updated = queue_store.retry_job(job_id)
    return queue_store.public_job(updated)


@app.delete("/queue/jobs/{job_id}")
def delete_queue_job(job_id: str):
    if not queue_store.delete_job(job_id):
        raise HTTPException(status_code=409, detail="Only finished jobs can be removed")
    cleanup_job_dir(job_id)
    return {"ok": True}


@app.delete("/queue/jobs")
def clear_finished_jobs():
    removed = queue_store.clear_terminal()
    return {"ok": True, "removed": removed}


@app.post("/queue/jobs/clear")
def clear_queue_jobs():
    jobs = queue_store.list_jobs()
    for job in jobs:
        kill_process(job["id"])
    removed_ids = queue_store.clear_all()
    for job_id in removed_ids:
        cleanup_job_dir(job_id)
    return {"ok": True, "removed": len(removed_ids)}


# ---------------------------------------------------------------------------
# Legacy endpoints (kept for compatibility; UI should use /queue/*)
# ---------------------------------------------------------------------------


@app.post("/download", response_model=DownloadResp)
def download(req: DownloadReq):
    """Legacy: enqueue as oneOff and return job id immediately."""
    job = queue_store.create_job(
        mode="oneOff",
        playlist_url=req.playlist_url,
        use_cookies=req.useCookies,
        album=req.album.model_dump(),
    )
    assert job is not None
    JOBS_DIR.joinpath(job["id"]).mkdir(parents=True, exist_ok=True)
    return DownloadResp(job_id=job["id"], out_dir=str(JOBS_DIR / job["id"]), tracks=[])


@app.get("/download/result/{job_id}", response_model=DownloadResp)
def get_download_result(job_id: str):
    job = queue_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail=f"Download failed: {job.get('error') or 'Unknown error'}")
    if job["status"] not in {"readyForReview", "completed", "finalizing"}:
        raise HTTPException(status_code=202, detail="Job still in progress")
    tracks_data = (job.get("manifest") or {}).get("tracks") or []
    tracks = [TrackIn(**t) for t in tracks_data]
    return DownloadResp(job_id=job_id, out_dir=str(JOBS_DIR / job_id), tracks=tracks)


@app.get("/progress/{job_id}", response_model=ProgressResp)
def get_progress(job_id: str):
    job = queue_store.get_job(job_id)
    if not job:
        return ProgressResp(job_id=job_id, current=0, total=0, status="unknown", current_title=None)
    status = job["status"]
    if status == "readyForReview":
        status = "completed"
    elif status == "failed":
        status = "error"
    return ProgressResp(
        job_id=job_id,
        current=job.get("current") or 0,
        total=job.get("total") or 0,
        status=status,
        current_title=job.get("currentTitle"),
    )


@app.post("/finalize", response_model=FinalizeResp)
def finalize(req: FinalizeReq):
    album_title = sanitize(req.album.title)
    album_artist = sanitize(req.album.artist)
    try:
        tracks = prepare_tracks(
            req.job_id,
            req.album.model_dump(),
            [t.model_dump() for t in req.ordered_tracks],
            cover_base64=req.cover_base64,
        )
    except LibraryError as exc:
        raise _library_http(exc) from exc
    zip_path = create_zip(album_artist, album_title, tracks)
    cleanup_job_dir(req.job_id)
    return FinalizeResp(ok=True, zip_url=f"/download/{zip_path.name}", count=len(req.ordered_tracks))


@app.post("/finalize/library", response_model=LibraryFinalizeResp)
def finalize_library(req: FinalizeReq):
    try:
        tracks = prepare_tracks(
            req.job_id,
            req.album.model_dump(),
            [t.model_dump() for t in req.ordered_tracks],
            cover_base64=req.cover_base64,
        )
        library_dir = save_to_library(req.album.artist, req.album.title, tracks)
    except LibraryError as exc:
        raise _library_http(exc) from exc
    cleanup_job_dir(req.job_id)
    return LibraryFinalizeResp(ok=True, library_path=str(library_dir), count=len(req.ordered_tracks))


@app.get("/download/{zip_name}")
def serve_zip(zip_name: str):
    target = OUT_DIR / zip_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path=target, filename=zip_name, media_type="application/zip")
