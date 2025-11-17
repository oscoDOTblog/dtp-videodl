from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from pathlib import Path
import subprocess
import uuid
import zipfile
import base64
import re
import os
import logging
import threading
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
OUT_DIR = DATA_DIR / "out"

JOBS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# In-memory progress tracking
progress_store = defaultdict(dict)
progress_lock = threading.Lock()

app = FastAPI(title="Playlist2Album API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INVALID_CHARS = r'[<>:"/\\|?*\n\r\t]'


def sanitize(name: str) -> str:
    s = re.sub(INVALID_CHARS, " ", name).strip()
    s = re.sub(r"\s+", " ", s)
    return s or "untitled"


class AlbumMeta(BaseModel):
    title: str = Field(default="")
    artist: str = Field(default="")
    year: str = Field(default="")


class TrackIn(BaseModel):
    id: int
    path: str
    title: str


class DownloadReq(BaseModel):
    playlist_url: str
    album: AlbumMeta


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


class ProgressResp(BaseModel):
    job_id: str
    current: int
    total: int
    status: str
    current_title: Optional[str] = None


def run_download_with_progress(job_id: str, playlist_url: str, template: str):
    """Run yt-dlp and track progress"""
    cmd = [
        "yt-dlp",
        playlist_url,
        "-o", template,
        "--yes-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--ffmpeg-location", "/usr/bin/ffmpeg",
        "--progress",
    ]
    
    # Initialize progress (assume single video until we detect playlist)
    with progress_lock:
        progress_store[job_id] = {
            "current": 0,
            "total": 1,  # Default to 1 for single videos
            "status": "starting",
            "current_title": None,
        }
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    
    # Parse output for progress
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        
        logger.debug(f"yt-dlp output: {line}")
            
        # Look for playlist info: "[youtube:tab] Playlist X: Y videos"
        playlist_info_match = re.search(r'\[.*?\]\s+Playlist.*?(\d+)\s+videos?', line, re.IGNORECASE)
        if playlist_info_match:
            total = int(playlist_info_match.group(1))
            with progress_lock:
                if progress_store[job_id]["total"] == 0:
                    progress_store[job_id]["total"] = total
            logger.info(f"Found playlist with {total} videos")
        
        # Look for "[download] Downloading video X of Y"
        download_match = re.search(r'\[download\]\s+Downloading\s+video\s+(\d+)\s+of\s+(\d+)', line, re.IGNORECASE)
        if download_match:
            current = int(download_match.group(1))
            total = int(download_match.group(2))
            with progress_lock:
                progress_store[job_id]["current"] = current
                progress_store[job_id]["total"] = total
                progress_store[job_id]["status"] = "downloading"
            logger.info(f"Progress: {current}/{total}")
        
        # Look for "[download] Downloading item X of Y"
        item_match = re.search(r'\[download\]\s+Downloading\s+item\s+(\d+)\s+of\s+(\d+)', line, re.IGNORECASE)
        if item_match:
            current = int(item_match.group(1))
            total = int(item_match.group(2))
            with progress_lock:
                progress_store[job_id]["current"] = current
                progress_store[job_id]["total"] = total
                progress_store[job_id]["status"] = "downloading"
            logger.info(f"Progress: {current}/{total}")
        
        # Look for video title in various formats
        title_patterns = [
            r'\[download\]\s+Destination:\s+.+?-\s+(.+?)\.mp3',
            r'\[download\]\s+(.+?)\s+has already been downloaded',
            r'\[ExtractAudio\]\s+Destination:\s+.+?-\s+(.+?)\.mp3',
        ]
        for pattern in title_patterns:
            title_match = re.search(pattern, line)
            if title_match:
                title = title_match.group(1).strip()
                with progress_lock:
                    progress_store[job_id]["current_title"] = title
                logger.debug(f"Downloading: {title}")
                break
        
        # Look for completion indicators
        if "[download] 100%" in line or "[ExtractAudio]" in line:
            with progress_lock:
                # For single videos, mark as complete when we see 100%
                if progress_store[job_id]["total"] == 1 and progress_store[job_id]["current"] == 0:
                    progress_store[job_id]["current"] = 1
                    progress_store[job_id]["status"] = "downloading"
                    logger.debug("Single video download progress: 1/1")
                elif progress_store[job_id]["total"] > 1 and progress_store[job_id]["current"] < progress_store[job_id]["total"]:
                    progress_store[job_id]["current"] += 1
                    logger.debug(f"Incremented progress to {progress_store[job_id]['current']}")
    
    process.wait()
    
    if process.returncode != 0:
        with progress_lock:
            progress_store[job_id]["status"] = "error"
        raise subprocess.CalledProcessError(process.returncode, cmd)
    
    # Finalize progress - ensure single videos are marked complete
    with progress_lock:
        if progress_store[job_id]["total"] == 1 and progress_store[job_id]["current"] == 0:
            progress_store[job_id]["current"] = 1
        progress_store[job_id]["status"] = "completed"


def process_download_async(job_id: str, playlist_url: str, template: str):
    """Process download in background thread"""
    try:
        run_download_with_progress(job_id, playlist_url, template)
        logger.info(f"yt-dlp completed successfully for job {job_id}")
        
        # Build manifest
        job_dir = JOBS_DIR / job_id
        logger.info("Building track manifest...")
        mp3s = sorted(p for p in job_dir.glob("*.mp3"))
        logger.info(f"Found {len(mp3s)} MP3 files")
        
        # Store tracks in progress store for retrieval
        tracks = []
        for i, p in enumerate(mp3s, start=1):
            title = p.stem
            # Strip leading number prefix and dash if present
            # For playlists: "01 - Title" -> "Title"
            # For single videos: "00 - Title" -> "Title" or " - Title" -> "Title"
            # Handle both numbered prefix and plain dash prefix
            title = re.sub(r"^\d+\s*-\s*", "", title)  # Remove "01 - " or "00 - " prefix
            title = re.sub(r"^\s*-\s*", "", title)  # Remove " - " prefix if present (single videos)
            tracks.append({"id": i, "path": str(p), "title": title})
            logger.debug(f"Track {i}: {title}")
        
        with progress_lock:
            progress_store[job_id]["tracks"] = tracks
            progress_store[job_id]["status"] = "completed"
        
        logger.info(f"Download job {job_id} completed successfully with {len(tracks)} tracks")
    except Exception as e:
        logger.error(f"Download failed for job {job_id}: {e}")
        with progress_lock:
            progress_store[job_id]["status"] = "error"
            progress_store[job_id]["error"] = str(e)


@app.post("/download", response_model=DownloadResp)
def download(req: DownloadReq):
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting download job {job_id}")
    logger.info(f"Playlist URL: {req.playlist_url}")
    logger.info(f"Album metadata - Title: '{req.album.title}', Artist: '{req.album.artist}', Year: '{req.album.year}'")
    logger.info(f"Output directory: {job_dir}")

    # Use playlist index for stable initial order; convert to mp3
    # Template handles both playlists and single videos
    # For playlists: "01 - Title.mp3", for single videos: "00 - Title.mp3" (we'll clean this up)
    template = str(job_dir / "%(playlist_index)02d - %(title)s.%(ext)s")
    logger.info(f"Using template: {template}")

    # Start download in background thread
    thread = threading.Thread(
        target=process_download_async,
        args=(job_id, req.playlist_url, template)
    )
    thread.daemon = True
    thread.start()

    # Return immediately with job_id
    return DownloadResp(job_id=job_id, out_dir=str(job_dir), tracks=[])


@app.get("/download/result/{job_id}", response_model=DownloadResp)
def get_download_result(job_id: str):
    """Get the final download result once completed"""
    with progress_lock:
        progress = progress_store.get(job_id)
    
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if progress.get("status") == "error":
        error_msg = progress.get("error", "Unknown error")
        raise HTTPException(status_code=500, detail=f"Download failed: {error_msg}")
    
    if progress.get("status") != "completed":
        raise HTTPException(status_code=202, detail="Job still in progress")
    
    tracks_data = progress.get("tracks", [])
    tracks = [TrackIn(**t) for t in tracks_data]
    job_dir = JOBS_DIR / job_id
    
    return DownloadResp(job_id=job_id, out_dir=str(job_dir), tracks=tracks)


@app.post("/finalize", response_model=FinalizeResp)
def finalize(req: FinalizeReq):
    logger.info(f"Starting finalize job {req.job_id}")
    logger.info(f"Album metadata - Title: '{req.album.title}', Artist: '{req.album.artist}', Year: '{req.album.year}'")
    logger.info(f"Processing {len(req.ordered_tracks)} tracks")
    
    try:
        from mutagen.id3 import ID3, APIC, TIT2, TALB, TPE1, TDRC, TRCK
        from mutagen.mp3 import MP3
        logger.info("Mutagen imported successfully")
    except Exception as e:
        logger.error(f"Failed to import mutagen: {e}")
        raise HTTPException(status_code=500, detail=f"mutagen import error: {e}")

    job_dir = JOBS_DIR / req.job_id
    if not job_dir.exists():
        logger.error(f"Job directory not found: {job_dir}")
        raise HTTPException(status_code=404, detail="job_id not found")

    logger.info(f"Job directory exists: {job_dir}")

    cover_bytes = None
    if req.cover_base64:
        try:
            cover_bytes = base64.b64decode(req.cover_base64)
            logger.info(f"Cover image decoded successfully ({len(cover_bytes)} bytes)")
        except Exception as e:
            logger.error(f"Failed to decode cover image: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid cover image: {e}")
    else:
        logger.info("No cover image provided")

    album_title = sanitize(req.album.title)
    album_artist = sanitize(req.album.artist)
    album_year = req.album.year

    logger.info(f"Sanitized album title: '{album_title}', artist: '{album_artist}', year: '{album_year}'")

    # Tag and rename
    logger.info("Starting to tag and rename tracks...")
    for idx, t in enumerate(req.ordered_tracks, start=1):
        src = Path(t.path)
        if not src.exists():
            logger.error(f"Track file not found: {src}")
            raise HTTPException(status_code=400, detail=f"missing file: {src}")

        logger.debug(f"Processing track {idx}/{len(req.ordered_tracks)}: {t.title}")

        # Write ID3
        audio = MP3(src, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()

        audio.tags["TIT2"] = TIT2(encoding=3, text=sanitize(t.title))
        audio.tags["TALB"] = TALB(encoding=3, text=album_title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=album_artist)
        if album_year:
            audio.tags["TDRC"] = TDRC(encoding=3, text=album_year)
        audio.tags["TRCK"] = TRCK(encoding=3, text=str(idx))

        if cover_bytes:
            audio.tags["APIC"] = APIC(
                encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes
            )
            logger.debug(f"Added cover art to track {idx}")

        audio.save(v2_version=3)  # ID3v2.3 for max compatibility
        logger.debug(f"Saved ID3 tags for track {idx}")

        # Rename to NN - Title.mp3
        new_name = job_dir / f"{str(idx).zfill(2)} - {sanitize(t.title)}.mp3"
        if src != new_name:
            src.rename(new_name)
            logger.debug(f"Renamed track {idx} to {new_name.name}")
        req.ordered_tracks[idx - 1].path = str(new_name)

    logger.info("All tracks tagged and renamed successfully")

    # Zip album
    zip_name = f"{album_artist} - {album_title}.zip" if album_artist else f"{album_title}.zip"
    zip_path = OUT_DIR / sanitize(zip_name)
    logger.info(f"Creating ZIP file: {zip_path}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in req.ordered_tracks:
            p = Path(t.path)
            zf.write(p, arcname=p.name)
            logger.debug(f"Added to ZIP: {p.name}")

    zip_size = zip_path.stat().st_size
    logger.info(f"ZIP file created successfully ({zip_size} bytes)")
    logger.info(f"Finalize job {req.job_id} completed successfully")

    return FinalizeResp(
        ok=True,
        zip_url=f"/download/{zip_path.name}",
        count=len(req.ordered_tracks)
    )


@app.get("/progress/{job_id}", response_model=ProgressResp)
def get_progress(job_id: str):
    with progress_lock:
        progress = progress_store.get(job_id, {
            "current": 0,
            "total": 0,
            "status": "unknown",
            "current_title": None,
        })
    
    return ProgressResp(
        job_id=job_id,
        current=progress.get("current", 0),
        total=progress.get("total", 0),
        status=progress.get("status", "unknown"),
        current_title=progress.get("current_title"),
    )


@app.get("/download/{zip_name}")
def serve_zip(zip_name: str):
    logger.info(f"Serving ZIP file: {zip_name}")
    target = OUT_DIR / zip_name
    if not target.exists():
        logger.error(f"ZIP file not found: {target}")
        raise HTTPException(status_code=404, detail="not found")
    logger.info(f"ZIP file found, size: {target.stat().st_size} bytes")
    return FileResponse(
        path=target,
        filename=zip_name,
        media_type="application/zip"
    )

