---
name: Cookies Upload Mount
overview: Add a cookies upload flow on the first page, persist the uploaded `cookies.txt` under a mounted host path, expose last-upload timestamp to the UI, and apply the file automatically in yt-dlp commands.
todos:
  - id: backend-cookies-api
    content: Add cookies storage config, upload/status endpoints, and yt-dlp cookie flag integration
    status: pending
  - id: frontend-cookies-ui
    content: Add first-page cookies upload/status UI and integrate with new API routes
    status: pending
  - id: api-proxy-cookies-routes
    content: Add Next API proxy routes for cookies status and upload
    status: pending
  - id: compose-cookies-mount
    content: Mount /mnt/yuna/navidrome/data as /cookies and set COOKIES_DIR env var
    status: pending
  - id: verify-cookies-flow
    content: Validate upload/status + yt-dlp cookie usage and run lint/syntax checks
    status: pending
isProject: false
---

# Add Cookies Upload + Mounted Persistence

## Goal
Enable uploading YouTube `cookies.txt` from the first page, store it in a mounted path for deployment use, show the last upload timestamp in the UI, and use that cookie file in yt-dlp download/metadata requests.

## Backend changes
- Update [`/Users/argo/Code/dtp/dtp-videodl/api/main.py`](/Users/argo/Code/dtp/dtp-videodl/api/main.py):
  - Add config paths:
    - `COOKIES_DIR` (default `/cookies`)
    - `COOKIES_FILE` (`/cookies/youtube.cookies.txt`)
    - `COOKIES_META_FILE` (`/cookies/youtube.cookies.meta.json`)
  - Add endpoints:
    - `POST /cookies/upload`: accept uploaded text file, validate it resembles Netscape cookie format, save to `COOKIES_FILE`, and record `uploadedAt` in metadata file.
    - `GET /cookies/status`: return `{ hasCookies, uploadedAt }` from metadata (or filesystem mtime fallback if metadata missing).
  - Add helper `build_yt_dlp_cmd(...)` used by both metadata and download codepaths; append `--cookies <COOKIES_FILE>` when file exists.
  - Update existing yt-dlp calls in `metadata()` and `run_download_with_progress()` to use the helper so age-restricted videos work with uploaded cookies.

## Frontend changes
- Update [`/Users/argo/Code/dtp/dtp-videodl/ui/app/page.js`](/Users/argo/Code/dtp/dtp-videodl/ui/app/page.js):
  - Add first-page cookie upload UI near playlist URL area:
    - Upload button/input for `cookies.txt`
    - status text (e.g. `Last uploaded: ...` or `No cookies uploaded yet`)
  - On page load, fetch `/api/cookies/status` to render current state.
  - On upload, call `/api/cookies/upload`, then refresh status and show success/error message.
- Add Next API proxy routes:
  - [`/Users/argo/Code/dtp/dtp-videodl/ui/app/api/cookies/status/route.js`](/Users/argo/Code/dtp/dtp-videodl/ui/app/api/cookies/status/route.js)
  - [`/Users/argo/Code/dtp/dtp-videodl/ui/app/api/cookies/upload/route.js`](/Users/argo/Code/dtp/dtp-videodl/ui/app/api/cookies/upload/route.js)
  - Match current proxy pattern to backend (`API_BASE_INTERNAL`).

## Docker compose updates
- Update [`/Users/argo/Code/dtp/dtp-videodl/docker-compose.yml`](/Users/argo/Code/dtp/dtp-videodl/docker-compose.yml):
  - Add API env var:
    - `COOKIES_DIR=/cookies`
  - Add volume mount for cookies persistence:
    - `/mnt/yuna/navidrome/data:/cookies`

## Validation
- Functional checks:
  - Upload valid `cookies.txt` from first page and confirm status/last-upload timestamp appears.
  - Restart container and verify timestamp and cookie presence still reported (persistent mount).
  - Run metadata fetch and download for an age-restricted URL to confirm yt-dlp uses cookies.
- Safety checks:
  - Reject clearly invalid uploads with readable error.
  - Keep existing non-cookie flow working when no cookie file is uploaded.
- Run lints on touched JS files and syntax-check backend file.

## Notes
- Timestamp source priority: metadata file `uploadedAt` first, then cookie file modified time fallback.
- If mount is unavailable, behavior degrades safely: upload endpoint returns explicit error instead of silently failing.