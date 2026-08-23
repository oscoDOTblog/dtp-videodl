# Deploying VideoDL behind Runtipi (custom domain)

This runbook covers running the **standalone** VideoDL Compose stack on the
same host as [Runtipi](https://runtipi.io), reusing Runtipi’s Traefik for
HTTPS on a public hostname you own — the same pattern as dtp-tunes.

VideoDL is **not** installed from the Runtipi App Store and does **not** use
the dashboard “Expose app” switch. Traefik discovers the gateway via Docker
labels in [`docker-compose.runtipi.yml`](../docker-compose.runtipi.yml).

## Architecture

```
Client  →  DNS (videodl.example.com)
        →  Router :80/:443
        →  Runtipi Traefik (Let's Encrypt / myresolver)
        →  VideoDL gateway (nginx)
        →  web (Next.js) + api (FastAPI)
```

Only the `gateway` container joins `runtipi_tipi_main_network`. `web` and `api`
stay on the private Compose network.

The FastAPI API also binds to **127.0.0.1:8545** on the host for loopback-only
tasks (dtp-os cookie sync, diagnostics). It is not exposed on the public domain.

## Prerequisites

1. **Runtipi is running** and already owns host ports **80** and **443**.
2. Docker network exists:

   ```bash
   docker network ls | grep runtipi_tipi_main_network
   ```

3. You own a domain and can create DNS records.
4. Router can forward **TCP 80 and 443** to the Runtipi host.
5. dtp-tunes is reachable from the VideoDL container for scan handoff
   (`DTP_TUNES_API_URL`).

## DNS

1. Pick a dedicated hostname that does **not** collide with another Traefik
   `Host(...)` rule (e.g. `videodl.waifu.bond`, separate from dtp-tunes).
2. Create an **A** record pointing that hostname at your **public** IP.
3. If the zone is on Cloudflare, set the record to **DNS only** (grey cloud).

Confirm propagation:

```bash
dig +short videodl.example.com
```

## Configure secrets

```bash
cd /path/to/dtp-videodl
cp .env.example .env
```

Edit `.env` at minimum:

| Variable | Notes |
| --- | --- |
| `VIDEODL_DOMAIN` | Exact public hostname (no scheme), e.g. `videodl.example.com` |
| `SITE_PASSWORD` | Strong password for the Next.js login gate |
| `MUSIC_HOST_PATH` | Same host music folder as dtp-tunes |
| `DTP_TUNES_INGEST_TOKEN` | Shared secret with dtp-tunes for scan handoff |

The Runtipi overlay **overrides** `CORS_ORIGINS` and
`NEXT_PUBLIC_API_BASE_EXTERNAL` to `https://${VIDEODL_DOMAIN}`.

## Start

Validate the merged config first:

```bash
docker compose -f docker-compose.yml -f docker-compose.runtipi.yml config
```

Confirm:

- `gateway` lists both `default` and `runtipi` networks
- Traefik labels reference `${VIDEODL_DOMAIN}`

Then start:

```bash
docker compose -f docker-compose.yml -f docker-compose.runtipi.yml up -d --build
```

## Verify

```bash
# Traefik route (HTTPS)
curl -I "https://${VIDEODL_DOMAIN}/health"

# Loopback gateway (diagnostics)
curl -I "http://127.0.0.1:8547/health"

# Cookie sync endpoint (loopback only — dtp-os extension)
curl -I "http://127.0.0.1:8545/cookies/status"
```

Open `https://${VIDEODL_DOMAIN}` in a browser — you should see the VideoDL
login screen when `SITE_PASSWORD` is set.

## Password protection

VideoDL uses the same client-side gate as sway-drive:

- `SITE_PASSWORD` in `.env` enables the login screen
- Leave `SITE_PASSWORD` empty for local dev (no gate)
- Auth is UI-only; do not treat it as enterprise-grade security

For a private homelab deployment behind Traefik, this is sufficient to keep
casual visitors out.

## Cookie sync (dtp-os)

The dtp-os **VideoDL Cookies** tool POSTs to `http://127.0.0.1:8545/cookies/upload`
(loopback FastAPI port). This path is **not** on the public domain, so cookie
files never traverse the internet.

VideoDL must be running on the same host as Chrome for sync to work.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Traefik 404 / no router | Wrong domain env, gateway not on Runtipi network | Re-check `VIDEODL_DOMAIN`, `docker network inspect runtipi_tipi_main_network` |
| Certificate errors | DNS not propagated, port 80 blocked | Confirm A record, ensure WAN :80/:443 reach Traefik |
| Login loop | Wrong password | Check `SITE_PASSWORD` in `.env`, rebuild `web` service |
| CORS errors | Stale origins | Confirm Runtipi overlay is applied; `CORS_ORIGINS` should be `https://${VIDEODL_DOMAIN}` |
| Scan handoff fails | Token mismatch or dtp-tunes unreachable | Match `DTP_TUNES_INGEST_TOKEN`; set `DTP_TUNES_API_URL` to the dtp-tunes gateway origin reachable from Docker |
