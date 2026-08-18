"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import styles from "./page.module.css";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const ACTIVE = new Set([
  "queued",
  "downloading",
  "finalizing",
  "readyForReview",
  "savedScanPending",
]);

function statusLabel(status) {
  switch (status) {
    case "readyForReview":
      return "Ready for review";
    case "savedScanPending":
      return "Saved · scan pending";
    default:
      return status;
  }
}

export default function QueuePage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = async () => {
    try {
      const response = await fetch("/api/queue/jobs");
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to load queue");
      }
      const data = await response.json();
      setJobs(data.jobs || []);
      setError("");
    } catch (err) {
      setError(err.message || "Failed to load queue");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, []);

  const runAction = async (jobId, action) => {
    setBusyId(jobId || action);
    try {
      let response;
      if (action === "remove") {
        response = await fetch(`/api/queue/jobs/${jobId}`, { method: "DELETE" });
      } else if (action === "clear") {
        response = await fetch("/api/queue/jobs", { method: "DELETE" });
      } else if (action === "clearAll") {
        response = await fetch("/api/queue/jobs/clear", { method: "POST" });
      } else {
        response = await fetch(`/api/queue/jobs/${jobId}/${action}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{}",
        });
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Action failed");
      }
      await load();
    } catch (err) {
      setError(err.message || "Action failed");
    } finally {
      setBusyId(null);
    }
  };

  const hasTerminal = jobs.some((job) => TERMINAL.has(job.status));
  const hasActive = jobs.some((job) => ACTIVE.has(job.status));

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <div className={styles.headerRow}>
          <div>
            <h1 className={styles.title}>Current Queue</h1>
            <p className={styles.subtitle}>
              One-off and background downloads into DTP Tunes
            </p>
          </div>
          <div className={styles.headerActions}>
            <Link href="/" className={styles.linkButton}>
              New download
            </Link>
            {hasTerminal && hasActive && (
              <button
                className={styles.dangerButton}
                disabled={busyId !== null}
                onClick={() => runAction(null, "clear")}
              >
                Clear finished
              </button>
            )}
            {jobs.length > 0 && (
              <button
                className={styles.dangerButton}
                disabled={busyId !== null}
                onClick={() => {
                  if (
                    !window.confirm(
                      "Clear all jobs from the queue? In-progress downloads will be cancelled."
                    )
                  ) {
                    return;
                  }
                  runAction(null, "clearAll");
                }}
              >
                {busyId === "clearAll" ? "Clearing…" : "Clear queue"}
              </button>
            )}
          </div>
        </div>

        {loading && <div className={styles.loading}>Loading queue…</div>}
        {error && <div className={styles.error}>{error}</div>}

        {!loading && jobs.length === 0 && (
          <div className={styles.empty}>
            Queue is empty. Start a one-off download or add something from Home.
          </div>
        )}

        <div className={styles.list}>
          {jobs.map((job) => {
            const progress =
              job.total > 0 ? Math.min(100, Math.round((job.current / job.total) * 100)) : 0;
            const busy = busyId !== null;
            return (
              <article key={job.id} className={styles.card}>
                <div className={styles.cardTop}>
                  <div>
                    <h2 className={styles.albumTitle}>
                      {job.album?.title || "Untitled album"}
                    </h2>
                    <p className={styles.meta}>
                      {job.album?.artist || "Unknown artist"}
                      {job.album?.year ? ` · ${job.album.year}` : ""}
                      {" · "}
                      {job.mode === "oneOff" ? "One-off" : "Queue"}
                    </p>
                  </div>
                  <span className={`${styles.status} ${styles[`status_${job.status}`] || ""}`}>
                    {statusLabel(job.status)}
                  </span>
                </div>

                {(job.status === "downloading" || job.status === "queued") && (
                  <div className={styles.progressBlock}>
                    <div className={styles.progressText}>
                      {job.status === "queued"
                        ? "Waiting for worker…"
                        : `Downloading ${job.current || 0} of ${job.total || "?"} tracks`}
                    </div>
                    {job.currentTitle && (
                      <div className={styles.currentTitle}>Current: {job.currentTitle}</div>
                    )}
                    <div className={styles.progressBar}>
                      <div className={styles.progressFill} style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                )}

                {job.error && <div className={styles.jobError}>{job.error}</div>}
                {job.libraryPath && (
                  <div className={styles.meta}>Saved to library</div>
                )}

                <div className={styles.actions}>
                  {job.status === "readyForReview" && (
                    <Link href={`/order?jobId=${job.id}`} className={styles.primaryButton}>
                      Review & save
                    </Link>
                  )}
                  {(job.status === "queued" ||
                    job.status === "downloading" ||
                    job.status === "finalizing" ||
                    job.status === "savedScanPending") && (
                    <button
                      className={styles.secondaryButton}
                      disabled={busy}
                      onClick={() => runAction(job.id, "cancel")}
                    >
                      {busy ? "…" : "Cancel"}
                    </button>
                  )}
                  {(job.status === "failed" ||
                    job.status === "cancelled" ||
                    job.status === "savedScanPending") && (
                    <button
                      className={styles.secondaryButton}
                      disabled={busy}
                      onClick={() => runAction(job.id, "retry")}
                    >
                      {busy ? "…" : job.status === "savedScanPending" ? "Retry scan" : "Retry"}
                    </button>
                  )}
                  {TERMINAL.has(job.status) && (
                    <button
                      className={styles.dangerButton}
                      disabled={busy}
                      onClick={() => runAction(job.id, "remove")}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>

        {hasActive && <div className={styles.loading}>Refreshing active jobs…</div>}
      </main>
    </div>
  );
}
