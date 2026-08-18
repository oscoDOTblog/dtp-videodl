"""Track tagging, ZIP creation, and atomic library promotion."""

from __future__ import annotations

import base64
import logging
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from app.paths import (
    DATA_DIR,
    DTP_TUNES_API_URL,
    DTP_TUNES_INGEST_TOKEN,
    JOBS_DIR,
    MAX_LIBRARY_UPLOAD_BYTES,
    MAX_LIBRARY_UPLOAD_FILES,
    MUSIC_LIBRARY_ROOT,
    OUT_DIR,
)
from app.sanitize import sanitize

logger = logging.getLogger("videodl.library")

ALLOWED_MP3_EXTENSIONS = {".mp3"}
ALLOWED_COVER_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}


class LibraryError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _load_mp3(path: Path):
    try:
        from mutagen.id3 import ID3
        from mutagen.mp3 import MP3
    except Exception as exc:  # noqa: BLE001
        raise LibraryError(f"mutagen import error: {exc}", status_code=500) from exc

    try:
        audio = MP3(path, ID3=ID3)
    except Exception as exc:  # noqa: BLE001
        raise LibraryError(f"invalid mp3: {path.name}") from exc
    if audio.tags is None:
        audio.add_tags()
    return audio


def _id3_text(tags, key: str) -> str:
    if tags is None:
        return ""
    frame = tags.get(key)
    if frame is None:
        return ""
    text = getattr(frame, "text", None)
    if not text:
        return ""
    return str(text[0]).strip()


def _year_from_tdrc(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) >= 4:
        return digits[:4]
    return ""


def _is_under_library_root(path: Path) -> bool:
    resolved = path.resolve()
    root = MUSIC_LIBRARY_ROOT
    return resolved == root or root in resolved.parents


def resolve_album_dir(album_artist: str, album_title: str) -> Path:
    artist_dir = sanitize(album_artist) if album_artist else "Unknown Artist"
    album_dir = sanitize(album_title) if album_title else "Unknown Album"
    if artist_dir in {".", ".."}:
        artist_dir = "Unknown Artist"
    if album_dir in {".", ".."}:
        album_dir = "Unknown Album"
    target_dir = (MUSIC_LIBRARY_ROOT / artist_dir / album_dir).resolve()
    if not _is_under_library_root(target_dir):
        raise LibraryError("invalid library destination")
    return target_dir


def read_mp3_metadata(path: Path) -> dict:
    audio = _load_mp3(path)
    tags = audio.tags
    title = _id3_text(tags, "TIT2")
    artist = _id3_text(tags, "TPE1") or _id3_text(tags, "TPE2")
    album = _id3_text(tags, "TALB")
    year = _year_from_tdrc(_id3_text(tags, "TDRC") or _id3_text(tags, "TYER"))
    track = _id3_text(tags, "TRCK").split("/")[0].strip()
    return {
        "title": title,
        "artist": artist,
        "album": album,
        "year": year,
        "track": track,
    }


def library_mount_status() -> dict:
    ready = False
    try:
        MUSIC_LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
        probe = MUSIC_LIBRARY_ROOT / f".write-probe-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ready = True
    except OSError as exc:
        logger.warning("Music library mount is not writable: %s", exc)
    return {
        "ready": ready,
        "scanConfigured": bool(DTP_TUNES_API_URL and DTP_TUNES_INGEST_TOKEN),
    }


def _safe_mp3_filename(original_name: str, title: str, index: int) -> str:
    base = Path(original_name or "").name
    suffix = Path(base).suffix.lower()
    stem = Path(base).stem if suffix in ALLOWED_MP3_EXTENSIONS else ""
    cleaned = sanitize(stem)
    if cleaned and cleaned != "untitled":
        return f"{cleaned}.mp3"
    cleaned_title = sanitize(title) if title else f"Track {index}"
    return f"{str(index).zfill(2)} - {cleaned_title}.mp3"


def _cover_extension(cover_mime: str) -> str:
    return ALLOWED_COVER_TYPES.get((cover_mime or "").lower(), ".jpg")


def tag_mp3(
    path: Path,
    *,
    title: str,
    artist: str,
    album: str,
    year: str = "",
    track_number: str = "",
    cover_bytes: Optional[bytes] = None,
    cover_mime: str = "image/jpeg",
) -> None:
    from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1, TRCK

    audio = _load_mp3(path)
    audio.tags["TIT2"] = TIT2(encoding=3, text=title)
    audio.tags["TALB"] = TALB(encoding=3, text=album)
    audio.tags["TPE1"] = TPE1(encoding=3, text=artist)
    if year:
        audio.tags["TDRC"] = TDRC(encoding=3, text=year)
    if track_number:
        audio.tags["TRCK"] = TRCK(encoding=3, text=str(track_number))
    if cover_bytes:
        mime = cover_mime if cover_mime in ALLOWED_COVER_TYPES else "image/jpeg"
        if mime == "image/jpg":
            mime = "image/jpeg"
        audio.tags["APIC"] = APIC(
            encoding=3, mime=mime, type=3, desc="Cover", data=cover_bytes
        )
    audio.save(v2_version=3)


def add_tracks_to_library(
    album_artist: str,
    album_title: str,
    tracks: list[Path],
    cover_bytes: Optional[bytes] = None,
    cover_mime: str = "image/jpeg",
) -> Path:
    """Copy tracks into an album folder without deleting existing files."""
    target_dir = resolve_album_dir(album_artist, album_title)
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        for track in tracks:
            dest = target_dir / track.name
            if not _is_under_library_root(dest):
                raise LibraryError("invalid library destination")
            if dest.name.startswith("."):
                raise LibraryError(f"refusing hidden library file: {dest.name}")
            partial = target_dir / f".{track.name}.partial-{uuid.uuid4().hex}"
            shutil.copy2(track, partial)
            partial.replace(dest)

        if cover_bytes:
            cover_name = f"cover{_cover_extension(cover_mime)}"
            cover_dest = target_dir / cover_name
            if not _is_under_library_root(cover_dest):
                raise LibraryError("invalid library destination")
            partial = target_dir / f".{cover_name}.partial-{uuid.uuid4().hex}"
            partial.write_bytes(cover_bytes)
            partial.replace(cover_dest)
    except LibraryError:
        raise
    except OSError as exc:
        raise LibraryError(str(exc), status_code=500) from exc

    return target_dir


def ingest_uploaded_mp3s(
    uploads: list[tuple[str, bytes]],
    artist: str = "",
    album: str = "",
    year: str = "",
    cover_bytes: Optional[bytes] = None,
    cover_mime: str = "image/jpeg",
) -> dict:
    if not uploads:
        raise LibraryError("at least one mp3 is required")
    if len(uploads) > MAX_LIBRARY_UPLOAD_FILES:
        raise LibraryError(f"too many files (max {MAX_LIBRARY_UPLOAD_FILES})")

    staging_root = DATA_DIR / "uploads" / uuid.uuid4().hex
    staging_root.mkdir(parents=True, exist_ok=True)

    try:
        parsed: list[dict] = []
        for index, (original_name, payload) in enumerate(uploads, start=1):
            if not payload:
                raise LibraryError(f"empty file: {original_name or index}")
            if len(payload) > MAX_LIBRARY_UPLOAD_BYTES:
                raise LibraryError(
                    f"file too large: {original_name or index}", status_code=413
                )
            suffix = Path(original_name or "").suffix.lower()
            if suffix not in ALLOWED_MP3_EXTENSIONS:
                raise LibraryError(f"only mp3 files are allowed: {original_name or index}")

            staged = staging_root / f"{index:03d}.mp3"
            staged.write_bytes(payload)
            try:
                meta = read_mp3_metadata(staged)
            except LibraryError as exc:
                raise LibraryError(f"invalid mp3: {original_name or index}") from exc
            parsed.append(
                {
                    "path": staged,
                    "originalName": original_name,
                    "meta": meta,
                    "index": index,
                }
            )

        first_meta = parsed[0]["meta"]
        resolved_artist = (artist or "").strip() or first_meta.get("artist") or "Unknown Artist"
        resolved_album = (album or "").strip() or first_meta.get("album") or "Unknown Album"
        resolved_year = (year or "").strip() or first_meta.get("year") or ""

        tagged_paths: list[Path] = []
        for item in parsed:
            meta = item["meta"]
            title = meta.get("title") or Path(item["originalName"] or "").stem or f"Track {item['index']}"
            filename = _safe_mp3_filename(item["originalName"], title, item["index"])
            dest = staging_root / filename
            if dest.exists() and dest != item["path"]:
                dest = staging_root / f"{Path(filename).stem}-{item['index']}.mp3"
            if dest != item["path"]:
                item["path"].rename(dest)
            tag_mp3(
                dest,
                title=sanitize(title),
                artist=sanitize(resolved_artist),
                album=sanitize(resolved_album),
                year=resolved_year,
                track_number=meta.get("track") or str(item["index"]),
                cover_bytes=cover_bytes,
                cover_mime=cover_mime,
            )
            tagged_paths.append(dest)

        target_dir = add_tracks_to_library(
            resolved_artist,
            resolved_album,
            tagged_paths,
            cover_bytes=cover_bytes,
            cover_mime=cover_mime,
        )
        return {
            "libraryPath": target_dir,
            "artist": sanitize(resolved_artist) if resolved_artist else "Unknown Artist",
            "album": sanitize(resolved_album) if resolved_album else "Unknown Album",
            "count": len(tagged_paths),
        }
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


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
    target_dir = resolve_album_dir(album_artist, album_title)
    artist_root = target_dir.parent
    album_dir = target_dir.name

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
