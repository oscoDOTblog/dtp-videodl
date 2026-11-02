"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import styles from "../app/page.module.css";

let nextRowKey = 0;

const newRow = () => ({
  key: ++nextRowKey,
  url: "",
  entirePlaylist: true,
  status: "idle",
  error: "",
  title: "",
  artist: "",
  year: "",
  coverFileName: "",
  coverPreview: "",
  coverBase64: "",
  autoCoverBase64: "",
  expanded: false,
});

const urlLooksLikePlaylist = (url) => /[?&]list=/.test(url || "");

const stripPlaylistParams = (url) => {
  try {
    const parsed = new URL(url);
    parsed.searchParams.delete("list");
    parsed.searchParams.delete("index");
    return parsed.toString();
  } catch {
    return url;
  }
};

const effectiveUrl = (row) =>
  urlLooksLikePlaylist(row.url) && !row.entirePlaylist
    ? stripPlaylistParams(row.url)
    : row.url;

const cropDataUrlToSquare = (dataUrl, outputType = "image/jpeg") =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const size = Math.min(img.width, img.height);
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        reject(new Error("Failed to create canvas context"));
        return;
      }
      ctx.drawImage(
        img,
        (img.width - size) / 2,
        (img.height - size) / 2,
        size,
        size,
        0,
        0,
        size,
        size
      );
      resolve(canvas.toDataURL(outputType, 0.95));
    };
    img.onerror = reject;
    img.src = dataUrl;
  });

export default function BatchDownload({ useCookies, onUseCookiesChange }) {
  const [rows, setRows] = useState(() => [newRow()]);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [enqueueing, setEnqueueing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const router = useRouter();

  const updateRow = (key, patch) =>
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const removeRow = (key) =>
    setRows((prev) => (prev.length > 1 ? prev.filter((row) => row.key !== key) : prev));

  const loadDetails = async () => {
    const targets = rows.filter((row) => row.status === "idle" && row.url.trim());
    if (targets.length === 0 || detailsLoading || enqueueing) return;
    setDetailsLoading(true);
    setError("");
    setNotice("");
    for (const target of targets) {
      updateRow(target.key, { status: "loading", error: "" });
      try {
        const response = await fetch("/api/metadata", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ playlist_url: target.url.trim(), useCookies }),
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Failed to fetch metadata");
        }
        const data = await response.json();
        let autoCoverBase64 = "";
        let coverPreview = "";
        let coverFileName = "";
        if (data.cover_base64) {
          const cropped = await cropDataUrlToSquare(
            `data:image/jpeg;base64,${data.cover_base64}`,
            "image/jpeg"
          );
          autoCoverBase64 = cropped.split(",").pop() || "";
          coverPreview = cropped;
          coverFileName = "Auto-filled from source";
        }
        updateRow(target.key, {
          status: "loaded",
          title: data.title || "",
          artist: data.artist || "",
          year: data.year || "",
          autoCoverBase64,
          coverPreview,
          coverFileName,
          expanded: false,
        });
      } catch (err) {
        updateRow(target.key, { status: "failed", error: err.message || "Failed to load details" });
      }
    }
    setDetailsLoading(false);
  };

  const handleCoverFile = async (key, file) => {
    if (!file) return;
    try {
      const reader = new FileReader();
      const sourceDataUrl = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });
      const cropped = await cropDataUrlToSquare(sourceDataUrl, file.type || "image/jpeg");
      updateRow(key, {
        coverBase64: cropped.split(",").pop() || "",
        autoCoverBase64: "",
        coverPreview: cropped,
        coverFileName: file.name,
      });
    } catch (err) {
      updateRow(key, { error: err.message || "Failed to process cover image" });
    }
  };

  const enqueueAll = async () => {
    const loaded = rows.filter((row) => row.status === "loaded");
    if (loaded.length === 0 || detailsLoading || enqueueing) return;
    setEnqueueing(true);
    setError("");
    setNotice("");
    const failed = [];
    for (const row of loaded) {
      try {
        const response = await fetch("/api/queue/jobs", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            mode: "queue",
            playlistUrl: effectiveUrl(row),
            useCookies,
            album: { title: row.title, artist: row.artist, year: row.year },
            coverBase64: row.coverBase64 || row.autoCoverBase64 || null,
          }),
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Failed to enqueue");
        }
        updateRow(row.key, { status: "queued" });
      } catch (err) {
        failed.push(row.title || row.url);
        updateRow(row.key, { status: "loaded", error: err.message || "Failed to add to queue" });
      }
    }
    setEnqueueing(false);
    if (failed.length === 0) {
      router.push("/queue");
    } else {
      setError(`Could not add to queue: ${failed.join("; ")}`);
    }
  };

  const loadableCount = rows.filter((row) => row.status === "idle" && row.url.trim()).length;
  const loadedCount = rows.filter((row) => row.status === "loaded").length;
  const busy = detailsLoading || enqueueing;

  return (
    <div className={styles.form}>
      <div className={styles.formGroup}>
        <label className={styles.toggleRow} htmlFor="batchUseCookiesToggle">
          <input
            id="batchUseCookiesToggle"
            type="checkbox"
            className={styles.toggleInput}
            checked={useCookies}
            onChange={(e) => onUseCookiesChange(e.target.checked)}
            disabled={busy}
          />
          <span className={styles.toggleSlider} aria-hidden="true" />
          <span>Use uploaded cookies for metadata/download</span>
        </label>
      </div>

      {rows.map((row, index) => (
        <section key={row.key} className={styles.batchRow}>
          <div className={styles.batchRowTop}>
            <span className={styles.batchRowIndex}>{index + 1}</span>
            {row.status === "idle" ? (
              <input
                className={styles.input}
                type="url"
                placeholder="https://youtube.com/playlist?list=... or track URL"
                value={row.url}
                onChange={(e) =>
                  updateRow(row.key, {
                    url: e.target.value,
                    entirePlaylist: urlLooksLikePlaylist(e.target.value),
                  })
                }
                disabled={busy}
              />
            ) : (
              <div className={styles.batchRowTitle}>
                {row.title || row.url || "Untitled"}
                {row.artist ? ` — ${row.artist}` : ""}
              </div>
            )}
            <span className={`${styles.statusBadge} ${styles[`statusBadge_${row.status}`] || ""}`}>
              {row.status === "idle" && "Pending"}
              {row.status === "loading" && "Loading…"}
              {row.status === "loaded" && "Details loaded"}
              {row.status === "queued" && "Queued"}
              {row.status === "failed" && "Failed"}
            </span>
            {rows.length > 1 && row.status !== "loading" && !busy && (
              <button
                type="button"
                className={styles.rowRemove}
                onClick={() => removeRow(row.key)}
                aria-label={`Remove row ${index + 1}`}
              >
                Remove
              </button>
            )}
          </div>

          {row.status === "idle" && urlLooksLikePlaylist(row.url) && (
            <label className={styles.toggleRow} htmlFor={`batchPlaylist-${row.key}`}>
              <input
                id={`batchPlaylist-${row.key}`}
                type="checkbox"
                className={styles.toggleInput}
                checked={row.entirePlaylist}
                onChange={(e) => updateRow(row.key, { entirePlaylist: e.target.checked })}
                disabled={busy}
              />
              <span className={styles.toggleSlider} aria-hidden="true" />
              <span>Download entire playlist (off = just this video)</span>
            </label>
          )}

          {row.status === "loading" && (
            <div className={styles.loading}>
              <span className={styles.spinner} /> Loading details…
            </div>
          )}

          {row.status === "failed" && (
            <div className={styles.error}>
              {row.error || "Failed to load details."}{" "}
              <button
                type="button"
                className={styles.rowRemove}
                onClick={() => removeRow(row.key)}
                disabled={busy}
              >
                Remove from list
              </button>
            </div>
          )}

          {(row.status === "loaded" || row.status === "queued") && (
            <>
              <button
                type="button"
                className={styles.expandButton}
                onClick={() => updateRow(row.key, { expanded: !row.expanded })}
                disabled={row.status === "queued"}
              >
                {row.expanded ? "Collapse details" : "Expand & edit details"}
              </button>
              {row.expanded && (
                <div className={styles.rowFields}>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Album</label>
                    <input
                      className={styles.input}
                      type="text"
                      value={row.title}
                      onChange={(e) => updateRow(row.key, { title: e.target.value })}
                      disabled={busy || row.status === "queued"}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Artist</label>
                    <input
                      className={styles.input}
                      type="text"
                      value={row.artist}
                      onChange={(e) => updateRow(row.key, { artist: e.target.value })}
                      disabled={busy || row.status === "queued"}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Year</label>
                    <input
                      className={styles.input}
                      type="text"
                      inputMode="numeric"
                      value={row.year}
                      onChange={(e) => {
                        if (e.target.value === "" || /^\d+$/.test(e.target.value)) {
                          updateRow(row.key, { year: e.target.value });
                        }
                      }}
                      disabled={busy || row.status === "queued"}
                    />
                  </div>
                  <div className={styles.formGroup}>
                    <label className={styles.label}>Album cover</label>
                    <label className={styles.fileInputLabel}>
                      Upload
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => handleCoverFile(row.key, e.target.files?.[0])}
                        disabled={busy || row.status === "queued"}
                      />
                    </label>
                    {row.coverFileName && (
                      <div className={styles.fileName}>{row.coverFileName}</div>
                    )}
                    {row.coverPreview && (
                      <div className={styles.imagePreview}>
                        <img
                          src={row.coverPreview}
                          alt="Album cover preview"
                          className={styles.previewImage}
                        />
                      </div>
                    )}
                  </div>
                </div>
              )}
              {row.error && <div className={styles.error}>{row.error}</div>}
            </>
          )}
        </section>
      ))}

      {error && <div className={styles.error}>{error}</div>}
      {notice && <div className={styles.loading}>{notice}</div>}

      <div className={styles.actionRow}>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => setRows((prev) => [...prev, newRow()])}
          disabled={busy}
        >
          Add another URL
        </button>
        <button
          type="button"
          className={styles.button}
          onClick={loadDetails}
          disabled={busy || loadableCount === 0}
        >
          {detailsLoading ? "Loading details…" : `Load details (${loadableCount})`}
        </button>
      </div>

      {loadedCount > 0 && (
        <button
          type="button"
          className={styles.button}
          onClick={enqueueAll}
          disabled={busy || loadedCount === 0}
        >
          {enqueueing ? "Adding…" : `Add ${loadedCount} to queue`}
        </button>
      )}
    </div>
  );
}
