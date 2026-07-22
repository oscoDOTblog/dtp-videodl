"""Client for requesting a DTP Tunes library scan after saves."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from app.paths import DTP_TUNES_API_URL, DTP_TUNES_INGEST_TOKEN

logger = logging.getLogger("videodl.tunes")


class ScanRequestError(Exception):
    pass


def request_tunes_scan() -> None:
    if not DTP_TUNES_API_URL:
        raise ScanRequestError("DTP_TUNES_API_URL is not configured")
    if not DTP_TUNES_INGEST_TOKEN:
        raise ScanRequestError("DTP_TUNES_INGEST_TOKEN is not configured")

    url = f"{DTP_TUNES_API_URL}/api/internal/scan"
    req = urllib.request.Request(
        url,
        method="POST",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {DTP_TUNES_INGEST_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status >= 400:
                body = response.read().decode("utf-8", errors="replace")
                raise ScanRequestError(f"scan request failed ({response.status}): {body}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise ScanRequestError(f"scan request failed ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise ScanRequestError(f"scan request unreachable: {exc}") from exc
