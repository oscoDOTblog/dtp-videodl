# Playlist2Album

Download YouTube playlists as MP3 albums with custom metadata. A local desktop app built with Next.js UI and Python FastAPI backend.

## Features

- **Step 1**: Enter YouTube playlist URL and set album metadata (title, artist, year, cover art)
- **Step 2**: Reorder tracks and edit track titles
- **Final**: Download ZIP file with properly tagged MP3s ready for music apps

## Requirements

- Docker and Docker Compose
- YouTube playlist URL

## Quick Start

1. Clone this repository
2. Run with Docker Compose:

```bash
docker compose up --build
```

3. Open your browser to:
   - **UI**: http://localhost:3000
   - **API**: http://localhost:8000

## Project Structure

```
playlist2album/
├── docker-compose.yml    # Docker Compose configuration
├── api/                  # Python FastAPI backend
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py          # API endpoints (download, finalize)
├── ui/                   # Next.js frontend
│   ├── Dockerfile
│   ├── app/
│   │   ├── page.js      # Step 1: Form with playlist URL
│   │   ├── order/
│   │   │   └── page.js  # Step 2: Reorder tracks
│   │   └── api/         # Proxy routes to FastAPI
│   └── package.json
└── data/                 # Output directory (created automatically)
    ├── jobs/            # Working directory for downloads
    └── out/              # Final ZIP files
```

## Usage

1. **Enter Playlist URL**: Paste your YouTube playlist URL
2. **Set Album Metadata**: Fill in album title, artist, year, and optionally upload cover art
3. **Download**: Click "Fetch & Convert" - this downloads all videos as MP3s
4. **Reorder**: On the order page, drag tracks up/down or edit titles
5. **Finalize**: Click "Finalize & Download ZIP" to get your tagged album

## Technical Details

- **Backend**: FastAPI with `yt-dlp` for downloading and `mutagen` for MP3 tagging
- **Frontend**: Next.js 16 with CSS Modules (no TypeScript, no Tailwind)
- **Styling**: Netflix-style dark theme with hot pink accents
- **Metadata**: ID3v2.3 tags for maximum compatibility

## Notes

- All processing happens locally - no cloud uploads
- Ensure you have rights to download/convert the content
- YouTube ToS/copyright may prohibit downloading content
