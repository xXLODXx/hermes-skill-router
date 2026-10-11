"""Deterministic installed-skill catalog for v2."""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
from dataclasses import asdict
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
# Match the relevant Hermes skill-scanner exclusions without importing the
# host's skill_utils (plugins also run in standalone validation). In particular,
# curator archives are not installed skills and must never become candidates.
_EXCLUDED_DIRS = frozenset({
    ".git", ".github", ".hub", ".archive", ".curator_backups", ".locks",
    ".venv", "venv", "node_modules", "site-packages", "__pycache__",
    ".tox", ".nox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})


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
    found: list[Path] = []
    for root, dirs, filenames in os.walk(skills_dir, followlinks=True):
        dirs[:] = [d for d in dirs if d not in _EXCLUDED_DIRS]
        if "SKILL.md" in filenames:
            found.append(Path(root) / "SKILL.md")
    paths = tuple(sorted(found))
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


# Shared catalog cache: the in-process caches above still stat every SKILL.md
# on each call and start empty in every new process. With thousands of skills
# and several sessions starting at once, each process paid a full read. One
# JSON file per home lets processes share the last scan.
_LOCK_STALE_S = 120.0


def _mtime_ns(path: str) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:  # a dangling symlink or junction: the tree walk skips it too
        return None


def _signature(skills_dir: Path) -> list:
    """Cheap change marker: adding or removing a skill changes the mtime of its
    parent folder (the skills root or a category folder)."""
    with os.scandir(skills_dir) as entries:
        # os.stat, not entry.stat(): on NTFS the parent listing reports a
        # folder mtime with a delay, the folder itself is current.
        folders = sorted([e.name, _mtime_ns(e.path)] for e in entries if e.name not in _EXCLUDED_DIRS and e.is_dir())
    return [str(skills_dir), skills_dir.stat().st_mtime_ns, *folders]


def cached_catalog(skills_dir: Path, cache: Path) -> tuple[SkillRecord, ...]:
    """``scan_catalog`` shared across processes through ``cache``.

    Added or removed skills directly under the root or its first-level folders
    show up on the next call. Deeper tree changes and SKILL.md edits show up
    within ``SKILL_ROUTER_SCAN_TTL`` seconds (0 = no shared cache). On expiry,
    one process rescans under a lock while others serve the previous scan.
    A changed signature triggers a fresh scan for every caller, but only the
    lock owner may publish its snapshot to the shared cache.
    """
    ttl = _scan_ttl()
    if ttl == 0 or not skills_dir.is_dir():
        return scan_catalog(skills_dir)
    try:
        sig = _signature(skills_dir)
    except OSError:
        # A category can disappear between is_dir() and scandir/stat().
        # The per-file scanner already tolerates disappearing skill paths.
        return scan_catalog(skills_dir)
    records: tuple[SkillRecord, ...] = ()
    same = False
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        records = tuple(SkillRecord(**{**r, "tags": tuple(r["tags"])}) for r in data["records"])
        same = data["sig"] == sig
        if same and 0 <= time.time() - data["ts"] < ttl:  # a ts in the future (clock moved back) is stale
            return records
    except (OSError, ValueError, KeyError, TypeError):
        same = False
    if not same:
        _SCAN_CACHE.pop(str(skills_dir), None)  # the tree changed: the in-process walk is stale too
    lock = cache.with_name(cache.name + ".lock")
    owner = False
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists() and not 0 <= time.time() - lock.stat().st_mtime <= _LOCK_STALE_S:
            lock.unlink()  # left behind by a scanner that died (or stamped by a clock that moved)
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
        owner = True
    except FileExistsError:
        if same:
            return records  # another process is rescanning: serve the previous scan
    except OSError:
        pass
    try:
        fresh = scan_catalog(skills_dir)
        tmp = cache.with_name(f"{cache.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        if owner:
            with contextlib.suppress(OSError):
                tmp.write_text(
                    json.dumps({"sig": sig, "ts": time.time(), "records": [asdict(r) for r in fresh]}),
                    encoding="utf-8",
                )
                os.replace(tmp, cache)
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return fresh
    finally:
        if owner:
            with contextlib.suppress(OSError):
                lock.unlink()
