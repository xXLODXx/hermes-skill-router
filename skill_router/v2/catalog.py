"""Deterministic installed-skill catalog for v2."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .models import SkillRecord

_FRONT = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_NAME = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
_DESC = re.compile(r"^description:\s*[\"']?(.*?)[\"']?\s*$", re.MULTILINE)
_TAGS = re.compile(r"tags:\s*\[([^\]]*)\]", re.MULTILINE)

# Parsed-record cache keyed by (path, mtime_ns, size): the hook scans the full
# catalog every turn, so unchanged SKILL.md files are re-used instead of
# re-read. Entries for edited files get new keys automatically; the cache is
# cleared when it grows past the bound so deleted-skill keys cannot pile up.
_PARSE_CACHE: dict[tuple[str, int, int], SkillRecord] = {}
_MAX_PARSE_CACHE = 4096

# Walk cache: enumerating the tree (followlinks) costs ~17 ms on a 195-skill
# home and runs on every turn. The path list is refreshed at most every
# ``SKILL_ROUTER_SCAN_TTL`` seconds (default 15; 0 = walk on every call).
# Between walks, content edits are still picked up immediately: every known
# path is stat-checked per call through the per-file parse cache above.
_SCAN_CACHE: dict[str, tuple[float, tuple[Path, ...]]] = {}
_SCAN_TTL_DEFAULT = 15.0
_MAX_SCAN_CACHE = 16


def _scan_ttl() -> float:
    """Tree-walk TTL in seconds; ``SKILL_ROUTER_SCAN_TTL`` overrides (0 = off)."""
    raw = os.environ.get("SKILL_ROUTER_SCAN_TTL", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            return _SCAN_TTL_DEFAULT
        if value >= 0:
            return value
    return _SCAN_TTL_DEFAULT


def _skill_paths(skills_dir: Path) -> tuple[Path, ...]:
    """Sorted SKILL.md paths of the tree; the walk itself is TTL-cached."""
    key = str(skills_dir)
    now = time.monotonic()
    cached = _SCAN_CACHE.get(key)
    if cached is not None and now - cached[0] < _scan_ttl():
        return cached[1]
    paths = tuple(
        sorted(
            Path(root) / filename
            for root, _, filenames in os.walk(skills_dir, followlinks=True)
            for filename in filenames
            if filename == "SKILL.md"
        )
    )
    if len(_SCAN_CACHE) >= _MAX_SCAN_CACHE:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[key] = (now, paths)
    return paths


def _field(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _tags(text: str) -> tuple[str, ...]:
    match = _TAGS.search(text)
    if not match:
        return ()
    return tuple(
        item.strip().strip("\"'")
        for item in match.group(1).split(",")
        if item.strip()
    )


def _parse_skill(path: Path, skills_dir: Path) -> SkillRecord | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _PARSE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    front = _FRONT.search(text)
    metadata = front.group(1) if front else text[:2000]
    name = (_field(metadata, _NAME) or path.parent.name).strip()
    if not name:
        return None
    category = path.parent.parent.name if path.parent.parent != skills_dir else ""
    record = SkillRecord(
        name=name,
        category=category,
        description=_field(metadata, _DESC),
        tags=_tags(metadata),
        source=str(path),
    )
    if len(_PARSE_CACHE) >= _MAX_PARSE_CACHE:
        _PARSE_CACHE.clear()
    _PARSE_CACHE[key] = record
    return record


def scan_catalog(skills_dir: Path) -> tuple[SkillRecord, ...]:
    records: dict[str, SkillRecord] = {}
    if not skills_dir.is_dir():
        _SCAN_CACHE.pop(str(skills_dir), None)
        return ()
    for path in _skill_paths(skills_dir):
        record = _parse_skill(path, skills_dir)
        if record is None:
            continue
        key = record.canonical_name
        if not key or key in records:
            continue
        records[key] = record
    return tuple(records[key] for key in sorted(records))
