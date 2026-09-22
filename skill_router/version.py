"""Single-source plugin version.

``plugin.yaml`` is authoritative; the constant below is only the fallback for
environments where the manifest is unreadable (isolated loaders, tooling).
"""

from __future__ import annotations

import re
from pathlib import Path

_FALLBACK = "0.8.4"
_VERSION = re.compile(r'^version:\s*["\']?([^"\'\s]+)["\']?\s*$', re.MULTILINE)

_cached: str | None = None


def _read_manifest_version() -> str:
    try:
        text = (Path(__file__).resolve().parent.parent / "plugin.yaml").read_text(encoding="utf-8")
        match = _VERSION.search(text)
    except OSError:
        return _FALLBACK
    return match.group(1).strip() if match else _FALLBACK


def plugin_version() -> str:
    """Return the manifest version (cached, never raises)."""
    global _cached
    cached = _cached
    if cached is None:
        cached = _read_manifest_version()
        _cached = cached
    return cached
