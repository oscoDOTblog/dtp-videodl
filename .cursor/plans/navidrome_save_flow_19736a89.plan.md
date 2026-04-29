---
name: Navidrome Save Flow
overview: Add a second finalize action that saves tagged tracks directly into the Navidrome music mount (`/music/<artist>/<album>`) while keeping the existing ZIP download flow intact, and update Docker compose to mount the Navidrome music path into the API container.
todos:
  - id: backend-finalize-library
    content: Add reusable finalize helpers and new /finalize/library endpoint with overwrite semantics
    status: pending
  - id: frontend-library-button
    content: Add Save to Navidrome Library button and API proxy route
    status: pending
  - id: compose-music-mount
    content: Mount Navidrome music path into API container and configure MUSIC_LIBRARY_ROOT
    status: pending
  - id: verify-flows
    content: Verify both ZIP and Navidrome save flows and run lint checks
    status: pending
isProject: false
---

# Add Navidrome Save Destination

## Goal
Add a new user action on the order screen to save finalized tracks directly into Navidrome’s mounted music library, while preserving the current `Finalize & Download ZIP` flow.

## Backend changes
- Update [`/Users/argo/Code/dtp/dtp-videodl/api/main.py`](/Users/argo/Code/dtp/dtp-videodl/api/main.py) to support two finalize destinations:
  - Existing ZIP output (`/download/<zip>`)
  - New Navidrome library output (`/music/<artist>/<album>`)
- Refactor current finalize logic into reusable helpers:
  - `apply_tags_and_track_order(...)` for tagging/renaming in job dir
  - `build_zip(...)` for current ZIP behavior
  - `save_to_library(...)` for copying/moving tracks into `/music/<artist>/<album>`
- Add a new endpoint (e.g. `POST /finalize/library`) that:
  - Reuses same request body (`job_id`, `album`, `ordered_tracks`, `cover_base64`)
  - Creates target dir with sanitized artist/album names
  - Writes tracks to target path with overwrite behavior (replace existing files)
  - Returns success payload including library path and count
- Keep all paths constrained under configured root mount (`MUSIC_LIBRARY_ROOT`, default `/music`) to avoid unsafe path writes.

## UI/API route changes
- Update [`/Users/argo/Code/dtp/dtp-videodl/ui/app/order/page.js`](/Users/argo/Code/dtp/dtp-videodl/ui/app/order/page.js):
  - Keep existing `Finalize & Download ZIP` button/flow.
  - Add second button: `Save to Navidrome Library`.
  - Wire new action to `/api/finalize/library` and show completion/error message.
  - Prevent double-submit and share loading state cleanly between both actions.
- Add new Next API proxy route at [`/Users/argo/Code/dtp/dtp-videodl/ui/app/api/finalize/library/route.js`](/Users/argo/Code/dtp/dtp-videodl/ui/app/api/finalize/library/route.js) mirroring existing proxy pattern.

## Docker compose updates
- Update [`/Users/argo/Code/dtp/dtp-videodl/docker-compose.yml`](/Users/argo/Code/dtp/dtp-videodl/docker-compose.yml):
  - Add Navidrome music host mount to API service:
    - `/mnt/yuna/navidrome:/music`
  - Add environment variable for clarity/configurability:
    - `MUSIC_LIBRARY_ROOT=/music`
- Keep existing API/UI external ports and current local setup unchanged.

## Validation
- Manual verification flow:
  - Enter URL -> fetch metadata -> download tracks -> open order page.
  - Test `Finalize & Download ZIP` still downloads correctly.
  - Test `Save to Navidrome Library` creates/updates `/music/<artist>/<album>` inside container (host: `/mnt/yuna/navidrome/<artist>/<album>`).
  - Confirm overwrite behavior replaces existing same-name tracks.
- Run lints for touched frontend/backend files and fix any introduced diagnostics.

## Notes on target path
- Based on your compose mount (`/mnt/yuna/navidrome:/music`), app writes under container `/music/<artist>/<album>` which maps to host `/mnt/yuna/navidrome/<artist>/<album>`.
- If you want host output strictly under `/mnt/yuna/navidrome/music/...`, we can switch mount to `/mnt/yuna/navidrome/music:/music` in a follow-up adjustment.