"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import styles from "./page.module.css";

export default function Home() {
  const [playlistUrl, setPlaylistUrl] = useState("");
  const [albumTitle, setAlbumTitle] = useState("");
  const [albumArtist, setAlbumArtist] = useState("");
  const [year, setYear] = useState("");
  const [cover, setCover] = useState(null);
  const [coverFileName, setCoverFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
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

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
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
      const coverBase64 = cover ? await toBase64(cover) : null;

      sessionStorage.setItem(
        "p2a-manifest",
        JSON.stringify({
          ...data,
          album: {
            title: albumTitle,
            artist: albumArtist,
            year: year,
          },
          coverBase64,
        })
      );

      router.push("/order");
    } catch (err) {
      setError(err.message || "Failed to download playlist");
      setLoading(false);
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setCover(file);
      setCoverFileName(file.name);
    } else {
      setCover(null);
      setCoverFileName("");
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
              onChange={(e) => setPlaylistUrl(e.target.value)}
              required
              disabled={loading}
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="albumTitle">
              Album Title
            </label>
            <input
              id="albumTitle"
              className={styles.input}
              type="text"
              placeholder="My Awesome Album"
              value={albumTitle}
              onChange={(e) => setAlbumTitle(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="albumArtist">
              Album Artist
            </label>
            <input
              id="albumArtist"
              className={styles.input}
              type="text"
              placeholder="Artist Name"
              value={albumArtist}
              onChange={(e) => setAlbumArtist(e.target.value)}
              disabled={loading}
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
              placeholder="2024"
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
              disabled={loading}
              min="1900"
              max="2100"
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="cover">
              Album Cover Art
            </label>
            <label className={styles.fileInputLabel} htmlFor="cover">
              {coverFileName || "Choose Image File"}
              <input
                id="cover"
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                disabled={loading}
              />
            </label>
            {coverFileName && (
              <div className={styles.fileName}>{coverFileName}</div>
            )}
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button
            type="submit"
            className={styles.button}
            disabled={loading || !playlistUrl}
          >
            {loading ? "Downloading..." : "Fetch & Convert"}
          </button>

          {loading && (
            <div className={styles.loading}>
              Downloading playlist... This may take a while.
            </div>
          )}
        </form>
      </main>
    </div>
  );
}

