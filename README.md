# VideoDL

Download playlists and tracks from YouTube, SoundCloud, and other yt-dlp-supported sites as MP3 albums, then save them into the shared **DTP Tunes** music library. Next.js UI + Python FastAPI backend with a durable SQLite download queue.

## Features

- **Load metadata**: Paste a playlist/track URL and review/edit album metadata and cover art
- **One-off download**: Download with live progress → reorder/edit tracks → **Save to DTP Tunes**
- **Queue mode**: Add jobs to a durable background queue; the worker tags, atomically saves, and requests a DTP Tunes library scan automatically
- **Current Queue** page with progress, cancel, retry, and history cleanup
- **Upload** page to drop existing MP3s into the mounted Navidrome / DTP Tunes library
- Shared host music folder with dtp-tunes via `MUSIC_HOST_PATH`

## Requirements

- Docker and Docker Compose
- A playlist or track URL from a supported site
- The same host music path as dtp-tunes (`MUSIC_HOST_PATH`)
- Matching `DTP_TUNES_INGEST_TOKEN` in both projects when scan handoff is enabled

## Quick Start

1. Copy `.env.example` to `.env` and set:

```bash
MUSIC_HOST_PATH=/Users/argo/Music/Navidrome   # must match dtp-tunes
DTP_TUNES_API_URL=http://host.docker.internal:8080
DTP_TUNES_INGEST_TOKEN=replace-with-a-long-random-shared-secret
```

2. Start:

```bash
# Local defaults (music bind under ./data/library if MUSIC_HOST_PATH unset)
docker compose -f docker-compose.local.yml up --build

# Production-style compose (requires MUSIC_HOST_PATH)
docker compose up --build
```

3. Open:
   - **Local dev**: http://localhost:8546 (direct web port; no password unless `SITE_PASSWORD` is set)
   - **Production gateway** (loopback): http://127.0.0.1:8547
   - **API** (loopback only, cookie sync): http://127.0.0.1:8545

## Public hostname (Runtipi / Traefik)

To expose VideoDL on a custom domain like dtp-tunes (e.g. `videodl.waifu.bond`):

1. Set in `.env`:

```bash
VIDEODL_DOMAIN=videodl.example.com
SITE_PASSWORD=your-secure-password
```

2. Create a DNS **A record** for `VIDEODL_DOMAIN` → your public IP.

3. Start with the Runtipi overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.runtipi.yml up -d --build
```

4. Open `https://videodl.example.com` — sign in with `SITE_PASSWORD`.

See [`docs/RUNTIPI_DEPLOYMENT.md`](docs/RUNTIPI_DEPLOYMENT.md) for full DNS, Traefik, and troubleshooting steps.

## Password protection

When `SITE_PASSWORD` is set in `.env`, the Next.js UI shows a login screen (same
pattern as sway-drive). Leave it empty for local dev with no gate.

- Auth is UI-only (`localStorage` flag after `POST /api/auth`)
- The FastAPI API on loopback (`127.0.0.1:8545`) is separate — used by dtp-os cookie sync
- Rebuild/restart the `web` service after changing `SITE_PASSWORD`

## YouTube cookies (local)

yt-dlp uses `./data/cookies/youtube.cookies.txt` when that file exists (`COOKIES_DIR`).

**Recommended (local Chrome):** open the dtp-os toolbar → **VideoDL Cookies** → **Sync now**. Stay signed in to YouTube in that Chrome profile. Optional auto-sync every 6 hours. The extension POSTs a Netscape cookie file to `http://127.0.0.1:8545/cookies/upload` — cookies never go through the Next.js UI.

**Manual:** export a Netscape `cookies.txt` and upload it on the home page.

VideoDL must be running for a sync to land. YouTube bot-checks can still fail even with fresh cookies.

## Download modes

| Mode | Behavior |
|------|----------|
| **One-off** | Enqueues `mode=oneOff`, polls that job, opens `/order?jobId=…` at `readyForReview`, then `POST /queue/jobs/{id}/save` |
| **Queue** | Enqueues `mode=queue`, resets the home form immediately, stays on `/`. Worker uses source order, tags, saves, then requests scan |

## Queue lifecycle

```
queued → downloading → readyForReview          # one-off (manual save)
queued → downloading → finalizing → savedScanPending → completed  # queue auto-save
failed / cancelled                             # terminal
```

- Startup recovers stale `downloading` / `finalizing` leases back to `queued` (scan-pending stays scan-pending).
- Cancel stops queued jobs immediately and terminates an active yt-dlp process when possible.
- Retry requeues `failed` / `cancelled` jobs; `savedScanPending` can retry scan without re-downloading.
- Durable state lives at `${DATA_DIR}/queue.sqlite3` (WAL). Back up that file with `data/` if you care about in-flight history.

## Shared library + scan handoff

1. Mount the **same** host folder into VideoDL RW (`/music`) and dtp-tunes RO (`/music`).
2. Configure a shared bearer token (`DTP_TUNES_INGEST_TOKEN`) in both stacks.
3. After an atomic album save, VideoDL calls `POST ${DTP_TUNES_API_URL}/api/internal/scan`.
4. If files saved but the scan call failed, the job stays `savedScanPending` and can be retried; the periodic dtp-tunes scanner remains a fallback.
5. dtp-tunes skips hidden staging/backup directories (names starting with `.`) so coincident scans never index partial writes.

## Upload MP3s

Open **Upload** in the header (`/upload`) to copy existing MP3s into the mounted library without going through yt-dlp.

- Drop or choose `.mp3` files. Artist / album / year are optional; blank fields use ID3 tags, then `Unknown Artist` / `Unknown Album`.
- Files are merged into `/music/<artist>/<album>/` (host: `$MUSIC_HOST_PATH/<artist>/<album>/`). Same-name tracks are replaced; other tracks in that album folder are kept.
- Optional JPEG/PNG cover is embedded and written as `cover.jpg` / `cover.png`.
- After a successful copy, VideoDL requests a DTP Tunes scan. If the scan call fails, the files are still on disk and the next periodic scan will pick them up.
- Browser APIs do not return host filesystem paths.

## Project structure

```
dtp-videodl/
├── docker-compose.yml / docker-compose.local.yml / docker-compose.runtipi.yml
├── gateway/nginx.conf          # nginx reverse proxy (production)
├── docs/RUNTIPI_DEPLOYMENT.md  # custom domain + Traefik runbook
├── api/
│   ├── main.py                 # REST + legacy endpoints
│   └── app/
│       ├── queue_store.py       # SQLite queue
│       ├── queue_worker.py      # Bounded workers
│       ├── download_service.py
│       ├── library_service.py
│       └── tunes_client.py
├── ui/
│   ├── app/page.js             # Home (one-off + queue)
│   ├── app/order/              # One-off review / save
│   ├── app/queue/              # Current Queue
│   ├── app/upload/             # Direct MP3 library intake
│   └── components/AppHeader.js
└── data/                       # jobs/, out/, queue.sqlite3
```

## Development / tests

```bash
cd api && pip install -r requirements.txt httpx pytest
DATA_DIR=/tmp/videodl-test pytest -q
cd ../ui && npm ci && npm run lint && npm run build
```

## Security notes

- VideoDL has **no user authentication** on the FastAPI loopback API (`127.0.0.1:8545`).
- Set `SITE_PASSWORD` before exposing the web UI on a public hostname.
- Keep the API port loopback-only; do not forward 8545 on your router.
- API port `8545` and gateway diagnostic port `8547` are bound to `127.0.0.1` only.
- Do not expose filesystem paths or cookies through the browser APIs.
- The dtp-os VideoDL Cookies tool may POST a Netscape cookie file to the loopback API only (`http://127.0.0.1` / `http://localhost`).

## Notes

- All processing happens locally — no cloud uploads of your media
- Ensure you have rights to download/convert the content
- Site terms of service and copyright laws may prohibit downloading content
- “Completed” means files were saved and a scan was accepted, not that every track is already searchable in DTP Tunes
