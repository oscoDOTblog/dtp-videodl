"""Track tagging, ZIP creation, and atomic library promotion."""

from __future__ import annotations

import base64
import logging
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from app.paths import JOBS_DIR, MUSIC_LIBRARY_ROOT, OUT_DIR
from app.sanitize import sanitize

logger = logging.getLogger("videodl.library")


class LibraryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def prepare_tracks(
    job_id: str,
    album: dict,
    ordered_tracks: list[dict],
    cover_base64: Optional[str] = None,
    cover_path: Optional[str] = None,
) -> list[Path]:
    try:
        from mutagen.id3 import ID3, APIC, TIT2, TALB, TPE1, TDRC, TRCK
        from mutagen.mp3 import MP3
    except Exception as exc:  # noqa: BLE001
        raise LibraryError(f"mutagen import error: {exc}", status_code=500) from exc

    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        raise LibraryError("job_id not found", status_code=404)

    cover_bytes = None
    if cover_base64:
        try:
            cover_bytes = base64.b64decode(cover_base64)
        except Exception as exc:  # noqa: BLE001
            raise LibraryError(f"Invalid cover image: {exc}") from exc
    elif cover_path and Path(cover_path).exists():
        cover_bytes = Path(cover_path).read_bytes()

    album_title = sanitize(album.get("title") or "")
    album_artist = sanitize(album.get("artist") or "")
    album_year = album.get("year") or ""

    final_paths: list[Path] = []
    for idx, track in enumerate(ordered_tracks, start=1):
        src = Path(track["path"])
        if not src.exists():
            # Fall back to looking up by relative name in job dir.
            candidate = job_dir / src.name
            if candidate.exists():
                src = candidate
            else:
                raise LibraryError(f"missing file: {src}")

        audio = MP3(src, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()

        title = sanitize(track.get("title") or f"Track {idx}")
        audio.tags["TIT2"] = TIT2(encoding=3, text=title)
        audio.tags["TALB"] = TALB(encoding=3, text=album_title)
        audio.tags["TPE1"] = TPE1(encoding=3, text=album_artist)
        if album_year:
            audio.tags["TDRC"] = TDRC(encoding=3, text=album_year)
        audio.tags["TRCK"] = TRCK(encoding=3, text=str(idx))

        if cover_bytes:
            audio.tags["APIC"] = APIC(
                encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes
            )

        audio.save(v2_version=3)

        new_name = job_dir / f"{str(idx).zfill(2)} - {title}.mp3"
        if src != new_name:
            if new_name.exists() and new_name != src:
                new_name.unlink()
            src.rename(new_name)
        track["path"] = str(new_name)
        final_paths.append(new_name)

    return final_paths


def cleanup_job_dir(job_id: str) -> None:
    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return
    try:
        shutil.rmtree(job_dir, ignore_errors=False)
        logger.info("Cleaned up job directory: %s", job_dir)
    except OSError as exc:
        logger.warning("Failed to cleanup job directory %s: %s", job_dir, exc)


def create_zip(album_artist: str, album_title: str, tracks: list[Path]) -> Path:
    zip_name = f"{album_artist} - {album_title}.zip" if album_artist else f"{album_title}.zip"
    zip_path = OUT_DIR / sanitize(zip_name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for track in tracks:
            zf.write(track, arcname=track.name)
    return zip_path


def save_to_library(album_artist: str, album_title: str, tracks: list[Path]) -> Path:
    artist_dir = sanitize(album_artist) if album_artist else "Unknown Artist"
    album_dir = sanitize(album_title) if album_title else "Unknown Album"
    artist_root = (MUSIC_LIBRARY_ROOT / artist_dir).resolve()
    target_dir = (artist_root / album_dir).resolve()

    if MUSIC_LIBRARY_ROOT not in target_dir.parents and target_dir != MUSIC_LIBRARY_ROOT:
        raise LibraryError("invalid library destination")

    artist_root.mkdir(parents=True, exist_ok=True)
    staging_dir = artist_root / f".{album_dir}.staging-{uuid.uuid4().hex}"
    backup_dir = artist_root / f".{album_dir}.backup-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        for track in tracks:
            staged_path = staging_dir / track.name
            shutil.copy2(track, staged_path)

        if target_dir.exists():
            target_dir.rename(backup_dir)

        try:
            staging_dir.rename(target_dir)
        except Exception as exc:  # noqa: BLE001
            if backup_dir.exists() and not target_dir.exists():
                backup_dir.rename(target_dir)
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            raise LibraryError(
                f"failed to promote staged library album: {exc}", status_code=500
            ) from exc

        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    except LibraryError:
        raise
    except Exception as exc:  # noqa: BLE001
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise LibraryError(str(exc), status_code=500) from exc

    return target_dir


def save_cover_bytes(job_id: str, cover_base64: str) -> Path:
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    cover_path = job_dir / "cover.jpg"
    cover_path.write_bytes(base64.b64decode(cover_base64))
    return cover_path
