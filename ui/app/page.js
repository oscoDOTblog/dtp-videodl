"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import styles from "./page.module.css";

const ACTIVE_ONE_OFF_JOB_KEY = "videodl-active-one-off-job";

export default function Home() {
  const [playlistUrl, setPlaylistUrl] = useState("");
  const [useCookies, setUseCookies] = useState(false);
  const [albumTitle, setAlbumTitle] = useState("");
  const [albumArtist, setAlbumArtist] = useState("");
  const [year, setYear] = useState("");
  const [detailsVisible, setDetailsVisible] = useState(false);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [autoCoverBase64, setAutoCoverBase64] = useState("");
  const [cover, setCover] = useState(null);
  const [coverFileName, setCoverFileName] = useState("");
  const [coverPreview, setCoverPreview] = useState("");
  const [loading, setLoading] = useState(false);
  const [enqueueing, setEnqueueing] = useState(false);
  const [queueMessage, setQueueMessage] = useState("");
  const [cookiesLoading, setCookiesLoading] = useState(false);
  const [cookiesStatus, setCookiesStatus] = useState({ hasCookies: false, uploadedAt: null });
  const [cookiesMessage, setCookiesMessage] = useState("");
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ current: 0, total: 0, status: "", currentTitle: "" });
  const progressIntervalRef = useRef(null);
  const router = useRouter();

  const rememberActiveOneOffJob = (jobId) => {
    try {
      sessionStorage.setItem(ACTIVE_ONE_OFF_JOB_KEY, jobId);
    } catch {
      // The download still works when browser storage is unavailable.
    }
  };

  const forgetActiveOneOffJob = () => {
    try {
      sessionStorage.removeItem(ACTIVE_ONE_OFF_JOB_KEY);
    } catch {
      // Nothing else to clean up when browser storage is unavailable.
    }
  };

  const formatUploadedAt = (value) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  };

  const loadCookiesStatus = async () => {
    try {
      const response = await fetch("/api/cookies/status");
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      setCookiesStatus({
        hasCookies: Boolean(data.hasCookies),
        uploadedAt: data.uploadedAt || null,
      });
    } catch (err) {
      console.error("Failed to load cookies status:", err);
    }
  };

  const toBase64 = (file) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        const base64 = result.split(",").pop() || "";
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  const cropDataUrlToSquare = (dataUrl, outputType = "image/jpeg") => {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const size = Math.min(img.width, img.height);
        const startX = (img.width - size) / 2;
        const startY = (img.height - size) / 2;

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
          startX,
          startY,
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
  };

  const loadMetadata = async () => {
    if (!playlistUrl) return;

    setMetadataLoading(true);
    setError("");

    try {
      const response = await fetch("/api/metadata", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ playlist_url: playlistUrl, useCookies: useCookies }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Failed to fetch metadata" }));
        throw new Error(errorData.detail || "Failed to fetch metadata");
      }

      const data = await response.json();
      setAlbumTitle(data.title || "");
      setAlbumArtist(data.artist || "");
      setYear(data.year || "");

      if (data.cover_base64) {
        const sourceDataUrl = `data:image/jpeg;base64,${data.cover_base64}`;
        const croppedDataUrl = await cropDataUrlToSquare(sourceDataUrl, "image/jpeg");
        setAutoCoverBase64(croppedDataUrl.split(",").pop() || "");
        setCover(null);
        setCoverFileName("Auto-filled from source");
        setCoverPreview(croppedDataUrl);
      } else {
        setAutoCoverBase64("");
        setCover(null);
        setCoverFileName("");
        setCoverPreview("");
      }
    } catch (err) {
      setError(err.message || "Failed to fetch metadata");
    } finally {
      setDetailsVisible(true);
      setMetadataLoading(false);
    }
  };

  const startOver = () => {
    setPlaylistUrl("");
    setAlbumTitle("");
    setAlbumArtist("");
    setYear("");
    setUseCookies(false);
    setAutoCoverBase64("");
    setCover(null);
    setCoverFileName("");
    setCoverPreview("");
    setDetailsVisible(false);
    setError("");
    setQueueMessage("");
    setProgress({ current: 0, total: 0, status: "", currentTitle: "" });
  };

  const buildCoverBase64 = async () => {
    if (cover) return toBase64(cover);
    return autoCoverBase64 || null;
  };

  const enqueueJob = async (mode) => {
    const response = await fetch("/api/queue/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        mode,
        playlistUrl,
        useCookies,
        album: {
          title: albumTitle,
          artist: albumArtist,
          year,
        },
        coverBase64: await buildCoverBase64(),
      }),
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: "Failed to enqueue" }));
      throw new Error(errorData.detail || "Failed to enqueue");
    }
    return response.json();
  };

  const pollQueueJob = async (jobId) => {
    try {
      const response = await fetch(`/api/queue/jobs/${jobId}`);
      if (!response.ok) {
        if (response.status === 404) {
          forgetActiveOneOffJob();
          setLoading(false);
          setError("The active download could not be found.");
          return true;
        }
        return false;
      }
      const job = await response.json();
      setProgress({
        current: job.current || 0,
        total: job.total || 0,
        status: job.status || "",
        currentTitle: job.currentTitle || "",
      });

      if (job.status === "readyForReview") {
        forgetActiveOneOffJob();
        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current);
          progressIntervalRef.current = null;
        }
        showNotification("VideoDL ready", {
          body: "Download finished. Review track order next.",
          tag: "download-complete",
        });
        router.push(`/order?jobId=${jobId}`);
        return true;
      }

      if (job.status === "failed" || job.status === "cancelled") {
        forgetActiveOneOffJob();
        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current);
          progressIntervalRef.current = null;
        }
        setError(job.error || `Job ${job.status}`);
        setLoading(false);
        showNotification("Download Failed", {
          body: job.error || `Job ${job.status}`,
          tag: "download-error",
        });
        return true;
      }

      if (job.status === "completed") {
        forgetActiveOneOffJob();
        if (progressIntervalRef.current) {
          clearInterval(progressIntervalRef.current);
          progressIntervalRef.current = null;
        }
        setLoading(false);
        setQueueMessage("Download was already saved to the library.");
        return true;
      }
    } catch (err) {
      console.error("Error polling queue job:", err);
    }
    return false;
  };

  const startOneOff = async () => {
    if (!detailsVisible || metadataLoading || loading || enqueueing) return;
    setLoading(true);
    setError("");
    setQueueMessage("");
    setProgress({ current: 0, total: 0, status: "starting", currentTitle: "" });

    try {
      const job = await enqueueJob("oneOff");
      const jobId = job.id;
      rememberActiveOneOffJob(jobId);
      progressIntervalRef.current = setInterval(async () => {
        await pollQueueJob(jobId);
      }, 1000);
      await pollQueueJob(jobId);
    } catch (err) {
      setError(err.message || "Failed to start download");
      setLoading(false);
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
    }
  };

  const addToQueue = async () => {
    if (!detailsVisible || metadataLoading || loading || enqueueing) return;
    setEnqueueing(true);
    setError("");
    setQueueMessage("");
    try {
      const job = await enqueueJob("queue");
      setQueueMessage(`Added “${albumTitle || "Untitled"}” to the queue.`);
      showNotification("Added to queue", {
        body: albumTitle || job.id,
        tag: "queue-added",
      });
      startOver();
      setQueueMessage(`Added to queue. Track progress on Current Queue.`);
    } catch (err) {
      setError(err.message || "Failed to add to queue");
    } finally {
      setEnqueueing(false);
    }
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    // Default form submit uses one-off mode.
    await startOneOff();
  };

  // Request notification permission on mount
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch((err) => {
        console.log("Notification permission request failed:", err);
      });
    }
  }, []);

  useEffect(() => {
    loadCookiesStatus();
  }, []);

  // A one-off job is durable in the API. Resume following it if the page is
  // reloaded or remounted while the download is still running.
  useEffect(() => {
    let jobId = "";
    try {
      jobId = sessionStorage.getItem(ACTIVE_ONE_OFF_JOB_KEY) || "";
    } catch {
      return;
    }
    if (!jobId) return;

    setLoading(true);
    setProgress({ current: 0, total: 0, status: "reconnecting", currentTitle: "" });
    progressIntervalRef.current = setInterval(async () => {
      await pollQueueJob(jobId);
    }, 1000);
    pollQueueJob(jobId);

    return () => {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
    };
    // Recovery intentionally runs only once per mount. Re-running it when the
    // render-local polling function changes would create duplicate intervals.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Show browser notification
  const showNotification = (title, options = {}) => {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, {
        icon: "/favicon.ico",
        badge: "/favicon.ico",
        ...options,
      });
    }
  };

  // Cleanup interval on unmount
  useEffect(() => {
    return () => {
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
      }
    };
  }, []);

  const cropToSquare = (file) => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = async (e) => {
        try {
          const sourceDataUrl = e.target?.result;
          const outputType = file.type || "image/jpeg";
          const croppedDataUrl = await cropDataUrlToSquare(sourceDataUrl, outputType);
          const response = await fetch(croppedDataUrl);
          const blob = await response.blob();
          const croppedFile = new File([blob], file.name, {
            type: outputType,
            lastModified: Date.now(),
          });
          resolve(croppedFile);
        } catch (err) {
          reject(err);
        }
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (file) {
      try {
        setAutoCoverBase64("");
        // Crop to square
        const croppedFile = await cropToSquare(file);
        setCover(croppedFile);
        setCoverFileName(file.name);
        
        // Create preview URL from cropped image
        const reader = new FileReader();
        reader.onloadend = () => {
          setCoverPreview(reader.result);
        };
        reader.readAsDataURL(croppedFile);
      } catch (err) {
        console.error("Error cropping image:", err);
        setError("Failed to process image. Please try again.");
        // Fallback to original file
        setCover(file);
        setCoverFileName(file.name);
        const reader = new FileReader();
        reader.onloadend = () => {
          setCoverPreview(reader.result);
        };
        reader.readAsDataURL(file);
      }
    } else {
      setCover(null);
      setCoverFileName("");
      setCoverPreview("");
      setAutoCoverBase64("");
    }
  };

  const handleCookiesUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setCookiesLoading(true);
    setCookiesMessage("");
    setError("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/cookies/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Cookies upload failed" }));
        throw new Error(errorData.detail || "Cookies upload failed");
      }

      const data = await response.json();
      setCookiesStatus({
        hasCookies: Boolean(data.hasCookies),
        uploadedAt: data.uploadedAt || null,
      });
      setCookiesMessage("Cookies uploaded successfully");
      await loadCookiesStatus();
    } catch (err) {
      setError(err.message || "Failed to upload cookies");
    } finally {
      setCookiesLoading(false);
      e.target.value = "";
    }
  };

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <h1 className={styles.title}>Playlist → Album</h1>
        <p className={styles.subtitle}>
          Download playlists and tracks from YouTube, SoundCloud, and other supported sites as tagged MP3 albums
        </p>

        <form onSubmit={onSubmit} className={styles.form}>
          {!detailsVisible && (
            <>
              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="playlistUrl">
                  Playlist or track URL
                </label>
                <input
                  id="playlistUrl"
                  className={styles.input}
                  type="url"
                  placeholder="https://youtube.com/playlist?list=... or https://soundcloud.com/artist/sets/..."
                  value={playlistUrl}
                  onChange={(e) => {
                    setPlaylistUrl(e.target.value);
                    setDetailsVisible(false);
                  }}
                  required
                  disabled={loading || metadataLoading}
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="useCookiesToggle">
                  Download Mode
                </label>
                <label className={styles.toggleRow} htmlFor="useCookiesToggle">
                  <input
                    id="useCookiesToggle"
                    type="checkbox"
                    className={styles.toggleInput}
                    checked={useCookies}
                    onChange={(e) => setUseCookies(e.target.checked)}
                    disabled={loading || metadataLoading || cookiesLoading}
                  />
                  <span className={styles.toggleSlider} aria-hidden="true" />
                  <span>Use uploaded cookies for metadata/download</span>
                </label>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="cookiesUpload">
                  Cookies (optional)
                </label>
                <p className={styles.fileName}>
                  For age-restricted or login-required content on supported sites (e.g. YouTube). Local Chrome: sync from the dtp-os VideoDL Cookies tool instead of exporting cookies.txt.
                </p>
                <label className={styles.fileInputLabel} htmlFor="cookiesUpload">
                  {cookiesLoading ? "Uploading..." : "Upload Cookies"}
                  <input
                    id="cookiesUpload"
                    type="file"
                    accept=".txt,text/plain"
                    onChange={handleCookiesUpload}
                    disabled={loading || metadataLoading || cookiesLoading}
                  />
                </label>
                <div className={styles.fileName}>
                  {cookiesStatus.hasCookies
                    ? `Last uploaded: ${formatUploadedAt(cookiesStatus.uploadedAt)}`
                    : "No cookies uploaded yet"}
                </div>
                {cookiesMessage && <div className={styles.loading}>{cookiesMessage}</div>}
              </div>

              <button
                type="button"
                className={styles.button}
                onClick={loadMetadata}
                disabled={!playlistUrl || loading || metadataLoading}
              >
                Load URL Details
              </button>
            </>
          )}

          {metadataLoading && (
            <div className={styles.loadingPanel}>
              <div className={styles.spinner} />
              <div className={styles.loading}>Loading metadata...</div>
            </div>
          )}

          {detailsVisible && (
            <>
              <button
                type="button"
                className={styles.button}
                onClick={startOver}
                disabled={loading || metadataLoading}
              >
                Start Over
              </button>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="albumTitle">
                  Album
                </label>
                <input
                  id="albumTitle"
                  className={styles.input}
                  type="text"
                  placeholder="My Awesome Album"
                  value={albumTitle}
                  onChange={(e) => setAlbumTitle(e.target.value)}
                  disabled={loading || metadataLoading}
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="albumArtist">
                  Artist
                </label>
                <input
                  id="albumArtist"
                  className={styles.input}
                  type="text"
                  placeholder="Artist Name"
                  value={albumArtist}
                  onChange={(e) => setAlbumArtist(e.target.value)}
                  disabled={loading || metadataLoading}
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="year">
                  Year
                </label>
                <input
                  id="year"
                  className={styles.input}
                  type="number"
                  placeholder="2026"
                  value={year}
                  onChange={(e) => {
                    const value = e.target.value;
                    // Only allow digits
                    if (value === "" || /^\d+$/.test(value)) {
                      setYear(value);
                    }
                  }}
                  onKeyDown={(e) => {
                    // Prevent non-numeric characters
                    if (e.key !== "Backspace" && e.key !== "Delete" && e.key !== "Tab" && e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") {
                      if (!/^\d$/.test(e.key)) {
                        e.preventDefault();
                      }
                    }
                  }}
                  disabled={loading || metadataLoading}
                  min="1900"
                  max="2100"
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label} htmlFor="cover">
                  Album Cover Art
                </label>
                <label className={styles.fileInputLabel} htmlFor="cover">
                  Upload
                  <input
                    id="cover"
                    type="file"
                    accept="image/*"
                    onChange={handleFileChange}
                    disabled={loading || metadataLoading}
                  />
                </label>
                {coverFileName && (
                  <div className={styles.fileName}>{coverFileName}</div>
                )}
                {coverPreview && (
                  <div className={styles.imagePreview}>
                    <img
                      src={coverPreview}
                      alt="Album cover preview"
                      className={styles.previewImage}
                    />
                  </div>
                )}
              </div>
            </>
          )}

          {error && <div className={styles.error}>{error}</div>}
          {queueMessage && <div className={styles.loading}>{queueMessage}</div>}

          {detailsVisible && (
            <div className={styles.actionRow}>
              <button
                type="button"
                className={styles.button}
                onClick={startOneOff}
                disabled={loading || enqueueing || metadataLoading || !playlistUrl}
              >
                {loading ? "Downloading…" : "One-off download"}
              </button>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={addToQueue}
                disabled={loading || enqueueing || metadataLoading || !playlistUrl}
              >
                {enqueueing ? "Adding…" : "Add to queue"}
              </button>
            </div>
          )}

          {loading && (
            <div className={styles.loading}>
              <div className={styles.spinner} />
              {progress.total > 0 ? (
                <>
                  <div className={styles.progressText}>
                    Downloading {progress.current} of {progress.total} tracks...
                  </div>
                  {progress.currentTitle && (
                    <div className={styles.currentTitle}>
                      Current: {progress.currentTitle}
                    </div>
                  )}
                  <div className={styles.progressBar}>
                    <div
                      className={styles.progressFill}
                      style={{
                        width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </>
              ) : (
                <div>Starting download... This may take a while.</div>
              )}
            </div>
          )}
        </form>
      </main>
    </div>
  );
}
