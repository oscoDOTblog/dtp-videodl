"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import styles from "./page.module.css";

export default function Home() {
  const [playlistUrl, setPlaylistUrl] = useState("");
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
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ current: 0, total: 0, status: "", currentTitle: "" });
  const progressIntervalRef = useRef(null);
  const router = useRouter();

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

  const pollProgress = async (jobId) => {
    try {
      const response = await fetch(`/api/progress?jobId=${jobId}`);
      if (response.ok) {
        const progressData = await response.json();
        setProgress({
          current: progressData.current || 0,
          total: progressData.total || 0,
          status: progressData.status || "",
          currentTitle: progressData.current_title || "",
        });
        
        // If completed or error, stop polling
        if (progressData.status === "completed") {
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = null;
          }
          // Show notification when download completes
          showNotification("Playlist2Album Complete!", {
            body: `Downloaded ${progressData.current || progressData.total || 0} of ${progressData.total || 0} videos. Processing tracks...`,
            tag: "download-progress",
          });
          return true; // Signal completion
        }
        
        if (progressData.status === "error") {
          if (progressIntervalRef.current) {
            clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = null;
          }
          showNotification("Download Failed", {
            body: "There was an error downloading the playlist.",
            tag: "download-error",
          });
          return true; // Signal completion
        }
      }
    } catch (err) {
      console.error("Error polling progress:", err);
    }
    return false;
  };

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
        body: JSON.stringify({ playlist_url: playlistUrl }),
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
        setCoverFileName("Auto-filled from playlist");
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
    setAutoCoverBase64("");
    setCover(null);
    setCoverFileName("");
    setCoverPreview("");
    setDetailsVisible(false);
    setError("");
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!detailsVisible || metadataLoading) return;
    setLoading(true);
    setError("");
    setProgress({ current: 0, total: 0, status: "starting", currentTitle: "" });

    try {
      // Start download (this will return immediately with job_id)
      const response = await fetch("/api/download", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          playlist_url: playlistUrl,
          album: {
            title: albumTitle,
            artist: albumArtist,
            year: year,
          },
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Download failed" }));
        throw new Error(errorData.detail || "Download failed");
      }

      const data = await response.json();
      const jobId = data.job_id;

      // Poll for progress
      progressIntervalRef.current = setInterval(async () => {
        const completed = await pollProgress(jobId);
        if (completed) {
          // Wait a moment then fetch final result
          setTimeout(async () => {
            try {
              // Fetch the download result to get tracks
              const finalResponse = await fetch(`/api/download/result?jobId=${jobId}`);
              
              if (finalResponse.ok) {
                const finalData = await finalResponse.json();
                const coverBase64 = cover ? await toBase64(cover) : autoCoverBase64 || null;

                sessionStorage.setItem(
                  "p2a-manifest",
                  JSON.stringify({
                    ...finalData,
                    album: {
                      title: albumTitle,
                      artist: albumArtist,
                      year: year,
                    },
                    coverBase64,
                  })
                );

                // Show notification
                showNotification("Playlist2Album Complete!", {
                  body: `Successfully downloaded ${finalData.tracks?.length || 0} tracks. Ready to proceed to ordering.`,
                  tag: "download-complete",
                });

                router.push("/order");
              } else if (finalResponse.status === 202) {
                // Still processing, continue polling
                return;
              } else {
                const errorData = await finalResponse.json().catch(() => ({ detail: "Failed to get result" }));
                throw new Error(errorData.detail || "Failed to get download result");
              }
            } catch (err) {
              setError(err.message || "Failed to get download result");
              setLoading(false);
            }
          }, 1000);
        }
      }, 1000); // Poll every second

      // Also poll immediately
      await pollProgress(jobId);
    } catch (err) {
      setError(err.message || "Failed to download playlist");
      setLoading(false);
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
    }
  };

  // Request notification permission on mount
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch((err) => {
        console.log("Notification permission request failed:", err);
      });
    }
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

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <h1 className={styles.title}>Playlist → Album</h1>
        <p className={styles.subtitle}>
          Download YouTube playlists as MP3 albums with custom metadata
        </p>

        <form onSubmit={onSubmit} className={styles.form}>
          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="playlistUrl">
              YouTube Playlist URL
            </label>
            <input
              id="playlistUrl"
              className={styles.input}
              type="url"
              placeholder="https://www.youtube.com/playlist?list=..."
              value={playlistUrl}
              onChange={(e) => {
                setPlaylistUrl(e.target.value);
                setDetailsVisible(false);
              }}
              required
              disabled={loading || metadataLoading}
            />
          </div>

          <button
            type="button"
            className={styles.button}
            onClick={loadMetadata}
            disabled={!playlistUrl || loading || metadataLoading}
          >
            {metadataLoading ? "Loading metadata..." : "Load URL Details"}
          </button>

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

          <button
            type="submit"
            className={styles.button}
            disabled={loading || metadataLoading || !playlistUrl || !detailsVisible}
          >
            {loading ? "Downloading..." : "Fetch & Convert"}
          </button>

          {loading && (
            <div className={styles.loading}>
              {progress.total > 0 ? (
                <>
                  <div className={styles.progressText}>
                    Downloading {progress.current} of {progress.total} videos...
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

