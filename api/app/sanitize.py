"""Filename sanitization helpers."""

from __future__ import annotations

import re

INVALID_CHARS = r'[<>:"/\\|?*\n\r\t]'


def sanitize(name: str) -> str:
    s = re.sub(INVALID_CHARS, " ", name or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s or "untitled"
