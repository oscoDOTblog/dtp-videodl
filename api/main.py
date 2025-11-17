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

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
JOBS_DIR = DATA_DIR / "jobs"
OUT_DIR = DATA_DIR / "out"

JOBS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

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


@app.post("/download", response_model=DownloadResp)
def download(req: DownloadReq):
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Use playlist index for stable initial order; convert to mp3
    template = str(job_dir / "%(playlist_index)02d - %(title)s.%(ext)s")

    # yt-dlp call
    cmd = [
        "yt-dlp",
        req.playlist_url,
        "-o", template,
        "--yes-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--ffmpeg-location", "/usr/bin/ffmpeg",
        "--no-progress",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"yt-dlp failed: {e.stderr}")

    # Build manifest
    mp3s = sorted(p for p in job_dir.glob("*.mp3"))
    tracks = []
    for i, p in enumerate(mp3s, start=1):
        title = p.stem
        title = re.sub(r"^\d+\s*-\s*", "", title)  # strip "01 - "
        tracks.append(TrackIn(id=i, path=str(p), title=title))

    return DownloadResp(job_id=job_id, out_dir=str(job_dir), tracks=tracks)


@app.post("/finalize", response_model=FinalizeResp)
def finalize(req: FinalizeReq):
    try:
        from mutagen.id3 import ID3, APIC, TIT2, TALB, TPE1, TDRC, TRCK
        from mutagen.mp3 import MP3
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mutagen import error: {e}")

    job_dir = JOBS_DIR / req.job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="job_id not found")

    cover_bytes = None
    if req.cover_base64:
        try:
            cover_bytes = base64.b64decode(req.cover_base64)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid cover image: {e}")

    album_title = sanitize(req.album.title)
    album_artist = sanitize(req.album.artist)
    album_year = req.album.year

    # Tag and rename
    for idx, t in enumerate(req.ordered_tracks, start=1):
        src = Path(t.path)
        if not src.exists():
            raise HTTPException(status_code=400, detail=f"missing file: {src}")

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

        audio.save(v2_version=3)  # ID3v2.3 for max compatibility

        # Rename to NN - Title.mp3
        new_name = job_dir / f"{str(idx).zfill(2)} - {sanitize(t.title)}.mp3"
        if src != new_name:
            src.rename(new_name)
        req.ordered_tracks[idx - 1].path = str(new_name)

    # Zip album
    zip_name = f"{album_artist} - {album_title}.zip" if album_artist else f"{album_title}.zip"
    zip_path = OUT_DIR / sanitize(zip_name)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in req.ordered_tracks:
            p = Path(t.path)
            zf.write(p, arcname=p.name)

    return FinalizeResp(
        ok=True,
        zip_url=f"/download/{zip_path.name}",
        count=len(req.ordered_tracks)
    )


@app.get("/download/{zip_name}")
def serve_zip(zip_name: str):
    target = OUT_DIR / zip_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path=target,
        filename=zip_name,
        media_type="application/zip"
    )

