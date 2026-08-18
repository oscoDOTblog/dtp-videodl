"use client";

import { useEffect, useState } from "react";
import styles from "./page.module.css";

function formatBytes(value) {
  const size = Number(value) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function isMp3File(file) {
  const name = (file?.name || "").toLowerCase();
  return name.endsWith(".mp3") || file?.type === "audio/mpeg";
}

function mergeFiles(current, incoming) {
  const next = [...current];
  incoming.forEach((file) => {
    const exists = next.some(
      (item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified
    );
    if (!exists) next.push(file);
  });
  return next;
}

export default function UploadPage() {
  const [status, setStatus] = useState({ ready: false, scanConfigured: false });
  const [statusError, setStatusError] = useState("");
  const [files, setFiles] = useState([]);
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [year, setYear] = useState("");
  const [cover, setCover] = useState(null);
  const [coverPreview, setCoverPreview] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const loadStatus = async () => {
    try {
      const response = await fetch("/api/library/status");
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to load library status");
      }
      const data = await response.json();
      setStatus({
        ready: Boolean(data.ready),
        scanConfigured: Boolean(data.scanConfigured),
      });
      setStatusError("");
    } catch (err) {
      setStatusError(err.message || "Failed to load library status");
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const addFiles = (incoming) => {
    const selected = Array.from(incoming || []);
    const mp3s = selected.filter(isMp3File);
    const skipped = selected.length - mp3s.length;
    setFiles((current) => mergeFiles(current, mp3s));
    setResult(null);
    if (skipped > 0) {
      setError(`${skipped} file${skipped === 1 ? " was" : "s were"} skipped. Only MP3s can be added.`);
    } else {
      setError("");
    }
  };

  const onCoverChange = (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setCover(null);
      setCoverPreview("");
      return;
    }
    setCover(file);
    const reader = new FileReader();
    reader.onloadend = () => setCoverPreview(reader.result || "");
    reader.readAsDataURL(file);
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!files.length || submitting) return;

    setSubmitting(true);
    setError("");
    setResult(null);

    try {
      const formData = new FormData();
      files.forEach((file) => formData.append("files", file));
      formData.append("artist", artist.trim());
      formData.append("album", album.trim());
      formData.append("year", year.trim());
      if (cover) formData.append("cover", cover);

      const response = await fetch("/api/library/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        const message = Array.isArray(detail)
          ? detail.map((item) => item.msg || item).join(", ")
          : detail;
        throw new Error(message || "Failed to add MP3s to the library");
      }

      setResult(data);
      setFiles([]);
      setCover(null);
      setCoverPreview("");
    } catch (err) {
      setError(err.message || "Failed to add MP3s to the library");
    } finally {
      setSubmitting(false);
    }
  };

  const totalBytes = files.reduce((sum, file) => sum + (file.size || 0), 0);

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <div className={styles.headerRow}>
          <div>
            <h1 className={styles.title}>Upload MP3s</h1>
            <p className={styles.subtitle}>
              Drop MP3s into the mounted music library. Files are tagged and merged into
              Artist / Album folders, then DTP Tunes is asked to scan.
            </p>
          </div>
        </div>

        <section className={styles.statusRow} aria-live="polite">
          <div className={`${styles.pill} ${status.ready ? styles.pillOn : styles.pillOff}`}>
            <span className={styles.pillDot} />
            {status.ready ? "Music mount writable" : "Music mount unavailable"}
          </div>
          <div className={`${styles.pill} ${status.scanConfigured ? styles.pillOn : styles.pillOff}`}>
            <span className={styles.pillDot} />
            {status.scanConfigured ? "Library scan configured" : "Scan not configured"}
          </div>
        </section>
        {statusError && <div className={styles.error}>{statusError}</div>}

        <form className={styles.card} onSubmit={onSubmit}>
          <div
            className={`${styles.dropzone} ${dragOver ? styles.dropzoneActive : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(false);
              addFiles(event.dataTransfer.files);
            }}
          >
            <div className={styles.dropCopy}>
              <strong>Drop MP3s here</strong>
              <span>or choose files from disk. Existing album tracks are kept.</span>
            </div>
            <label className={styles.fileButton} htmlFor="mp3Upload">
              Choose MP3s
              <input
                id="mp3Upload"
                type="file"
                accept=".mp3,audio/mpeg"
                multiple
                onChange={(event) => {
                  addFiles(event.target.files);
                  event.target.value = "";
                }}
                disabled={submitting || !status.ready}
              />
            </label>
          </div>

          {files.length > 0 && (
            <div className={styles.tracklist}>
              <div className={styles.trackHead}>
                <span>
                  {files.length} track{files.length === 1 ? "" : "s"}
                </span>
                <span>{formatBytes(totalBytes)}</span>
              </div>
              <ol className={styles.tracks}>
                {files.map((file, index) => (
                  <li key={`${file.name}-${file.size}-${file.lastModified}`} className={styles.track}>
                    <span className={styles.trackIndex}>{String(index + 1).padStart(2, "0")}</span>
                    <span className={styles.trackName}>{file.name}</span>
                    <span className={styles.trackSize}>{formatBytes(file.size)}</span>
                    <button
                      type="button"
                      className={styles.removeButton}
                      onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                      disabled={submitting}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}

          <div className={styles.fields}>
            <div className={styles.formGroup}>
              <label className={styles.label} htmlFor="artist">
                Artist override
              </label>
              <input
                id="artist"
                className={styles.input}
                value={artist}
                onChange={(event) => setArtist(event.target.value)}
                placeholder="Leave blank to use ID3 tags"
                disabled={submitting}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.label} htmlFor="album">
                Album override
              </label>
              <input
                id="album"
                className={styles.input}
                value={album}
                onChange={(event) => setAlbum(event.target.value)}
                placeholder="Leave blank to use ID3 tags"
                disabled={submitting}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.label} htmlFor="year">
                Year
              </label>
              <input
                id="year"
                className={styles.input}
                value={year}
                onChange={(event) => setYear(event.target.value)}
                placeholder="Optional"
                disabled={submitting}
              />
            </div>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="coverUpload">
              Cover art
            </label>
            <label className={styles.fileInputLabel} htmlFor="coverUpload">
              {cover ? cover.name : "Upload JPEG or PNG"}
              <input
                id="coverUpload"
                type="file"
                accept="image/jpeg,image/png,.jpg,.jpeg,.png"
                onChange={onCoverChange}
                disabled={submitting}
              />
            </label>
            {coverPreview && (
              <div className={styles.imagePreview}>
                <img src={coverPreview} alt="Cover preview" className={styles.previewImage} />
              </div>
            )}
          </div>

          {error && <div className={styles.error}>{error}</div>}
          {result && (
            <div className={styles.success}>
              Added {result.count} track{result.count === 1 ? "" : "s"} to {result.artist} / {result.album}.
              {result.scanned
                ? " Library scan requested."
                : " Files are saved; scan could not be reached, so DTP Tunes will pick them up on its next scan."}
            </div>
          )}

          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.button}
              disabled={submitting || !status.ready || files.length === 0}
            >
              {submitting ? "Adding…" : "Add to library"}
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => {
                setFiles([]);
                setCover(null);
                setCoverPreview("");
                setError("");
                setResult(null);
              }}
              disabled={submitting || (files.length === 0 && !cover && !result)}
            >
              Clear
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
