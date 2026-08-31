"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import styles from "./page.module.css";

export default function OrderPage() {
  const searchParams = useSearchParams();
  const jobId = searchParams.get("jobId");
  const router = useRouter();

  const [job, setJob] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    if (!jobId) {
      setLoading(false);
      setError("Missing jobId");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`/api/queue/jobs/${jobId}`);
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.detail || "Failed to load job");
        }
        const data = await response.json();
        if (cancelled) return;
        setJob(data);
        setTracks(data.tracks || []);
        if (data.status !== "readyForReview") {
          setError(`Job is not ready for review (status: ${data.status})`);
        }
      } catch (err) {
        if (!cancelled) setError(err.message || "Failed to load job");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const canSave = useMemo(
    () => job?.status === "readyForReview" && tracks.length > 0 && !saving,
    [job, tracks, saving]
  );

  const move = (fromIndex, toIndex) => {
    const next = [...tracks];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    setTracks(next);
  };

  const updateTrackTitle = (index, newTitle) => {
    const next = [...tracks];
    next[index] = { ...next[index], title: newTitle };
    setTracks(next);
  };

  const saveToTunes = async () => {
    if (!jobId || !canSave) return;
    setSaving(true);
    setError("");
    setSuccessMessage("");
    try {
      const response = await fetch(`/api/queue/jobs/${jobId}/save`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          orderedTracks: tracks.map((track) => ({
            id: track.id,
            title: track.title,
            path: "",
          })),
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Save failed");
      }
      const data = await response.json();
      setJob(data.job);
      setSuccessMessage(`Saved ${data.count || tracks.length} tracks to DTP Tunes`);
    } catch (err) {
      setError(err.message || "Failed to save to DTP Tunes");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.container}>
        <main className={styles.main}>
          <div className={styles.loading}>Loading job…</div>
        </main>
      </div>
    );
  }

  if (!job) {
    return (
      <div className={styles.container}>
        <main className={styles.main}>
          <div className={styles.noManifest}>
            <h2 className={styles.title}>Job not found</h2>
            <p>{error || "Please start from the beginning."}</p>
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
        <div className={styles.topLinks}>
          <Link href="/" className={styles.homeButton}>
            Return to Home
          </Link>
          <Link href="/queue" className={styles.homeButton}>
            Current Queue
          </Link>
        </div>
        <h2 className={styles.title}>Set Track Order & Titles</h2>
        <p className={styles.subtitle}>
          {job.album?.title || "Untitled"} · {job.album?.artist || "Unknown artist"}
        </p>

        <div className={styles.tracksList}>
          {tracks.map((track, index) => (
            <div key={`${track.id}-${index}`} className={styles.trackItem}>
              <div className={styles.trackNumber}>{index + 1}</div>
              <input
                className={styles.trackInput}
                value={track.title}
                onChange={(e) => updateTrackTitle(index, e.target.value)}
                disabled={saving || job.status !== "readyForReview"}
              />
              <div className={styles.controls}>
                <button
                  className={styles.controlButton}
                  disabled={index === 0 || saving || job.status !== "readyForReview"}
                  onClick={() => move(index, index - 1)}
                  aria-label="Move up"
                >
                  ↑
                </button>
                <button
                  className={styles.controlButton}
                  disabled={
                    index === tracks.length - 1 || saving || job.status !== "readyForReview"
                  }
                  onClick={() => move(index, index + 1)}
                  aria-label="Move down"
                >
                  ↓
                </button>
              </div>
            </div>
          ))}
        </div>

        {error && job.status === "readyForReview" && <div className={styles.error}>{error}</div>}
        {error && job.status !== "readyForReview" && !successMessage && (
          <div className={styles.error}>{error}</div>
        )}
        {successMessage && <div className={styles.loading}>{successMessage}</div>}

        <div className={styles.finalizeSection}>
          {job.status === "readyForReview" ? (
            <button onClick={saveToTunes} className={styles.finalizeButton} disabled={!canSave}>
              {saving ? (
                <>
                  <span className={styles.spinner} /> Saving…
                </>
              ) : (
                "Save to DTP Tunes"
              )}
            </button>
          ) : (
            <div className={styles.loading}>
              Job status: {job.status}.{" "}
              <button className={styles.homeButton} onClick={() => router.push("/queue")}>
                Back to queue
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
