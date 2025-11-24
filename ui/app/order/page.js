"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import styles from "./page.module.css";

export default function OrderPage() {
  const [job, setJob] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  useEffect(() => {
    const manifest = sessionStorage.getItem("p2a-manifest");
    if (manifest) {
      try {
        const parsed = JSON.parse(manifest);
        setJob(parsed);
        setTracks(parsed.tracks || []);
      } catch (err) {
        setError("Failed to load manifest");
      }
    }
  }, []);

  const move = (fromIndex, toIndex) => {
    const newTracks = [...tracks];
    const [moved] = newTracks.splice(fromIndex, 1);
    newTracks.splice(toIndex, 0, moved);
    setTracks(newTracks);
  };

  const updateTrackTitle = (index, newTitle) => {
    const newTracks = [...tracks];
    newTracks[index] = { ...newTracks[index], title: newTitle };
    setTracks(newTracks);
  };

  const finalize = async () => {
    if (!job) return;

    setLoading(true);
    setError("");

    try {
      const response = await fetch("/api/finalize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          job_id: job.job_id,
          album: job.album,
          ordered_tracks: tracks,
          cover_base64: job.coverBase64 || null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Finalize failed" }));
        throw new Error(errorData.detail || "Finalize failed");
      }

      const data = await response.json();
      // Download the zip file
      window.location.href = `http://localhost:8000${data.zip_url}`;
    } catch (err) {
      setError(err.message || "Failed to finalize album");
      setLoading(false);
    }
  };

  if (!job) {
    return (
      <div className={styles.container}>
        <main className={styles.main}>
          <div className={styles.noManifest}>
            <h2 className={styles.title}>No manifest loaded</h2>
            <p>Please start from the beginning.</p>
            <Link href="/" className={styles.noManifestLink}>
              Go to Home
            </Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <Link href="/" className={styles.homeButton}>
          Return to Home
        </Link>
        <h2 className={styles.title}>Set Track Order & Titles</h2>
        <p className={styles.subtitle}>
          Reorder tracks and edit titles before finalizing your album
        </p>

        <div className={styles.tracksList}>
          {tracks.map((track, index) => (
            <div key={track.id} className={styles.trackItem}>
              <div className={styles.trackNumber}>{index + 1}</div>
              <input
                className={styles.trackInput}
                value={track.title}
                onChange={(e) => updateTrackTitle(index, e.target.value)}
                disabled={loading}
              />
              <div className={styles.controls}>
                <button
                  className={styles.controlButton}
                  disabled={index === 0 || loading}
                  onClick={() => move(index, index - 1)}
                  aria-label="Move up"
                >
                  ↑
                </button>
                <button
                  className={styles.controlButton}
                  disabled={index === tracks.length - 1 || loading}
                  onClick={() => move(index, index + 1)}
                  aria-label="Move down"
                >
                  ↓
                </button>
              </div>
            </div>
          ))}
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.finalizeSection}>
          <button
            onClick={finalize}
            className={styles.finalizeButton}
            disabled={loading || tracks.length === 0}
          >
            {loading ? "Finalizing..." : "Finalize & Download ZIP"}
          </button>
          {loading && (
            <div className={styles.loading}>
              Setting metadata and creating ZIP file...
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

