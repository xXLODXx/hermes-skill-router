"""Deterministic installed-skill catalog for v2."""

from __future__ import annotations

import contextlib
import importlib
import json
import math
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
_SUPPORT_DIRS = frozenset({"references", "templates", "assets", "scripts"})
_VISIBILITY_TTL_DEFAULT = 60.0


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


def _visibility_ttl() -> float:
    """Longer host-index TTL; zero scan TTL disables both shared caches."""
    if _scan_ttl() == 0:
        return 0.0
    raw = os.environ.get("SKILL_ROUTER_VISIBILITY_TTL", "").strip()
    try:
        value = float(raw) if raw else _VISIBILITY_TTL_DEFAULT
    except ValueError:
        return _VISIBILITY_TTL_DEFAULT
    return value if math.isfinite(value) and value >= 0 else _VISIBILITY_TTL_DEFAULT


def _skill_paths(skills_dir: Path) -> tuple[Path, ...]:
    """Sorted SKILL.md paths of the tree; the walk itself is TTL-cached."""
    key = str(skills_dir)
    now = time.monotonic()
    cached = _SCAN_CACHE.get(key)
    if cached is not None and now - cached[0] < _scan_ttl():
        return cached[1]
    found: list[Path] = []
    for root, dirs, filenames in os.walk(skills_dir, followlinks=True):
        excluded = _EXCLUDED_DIRS | (_SUPPORT_DIRS if "SKILL.md" in filenames else frozenset())
        dirs[:] = [d for d in dirs if d not in excluded]
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


def runtime_catalog(skills_dir: Path, cache: Path) -> tuple[SkillRecord, ...]:
    """Align suggestions with Hermes' resolved visible/loadable skill entries.

    Hermes resolves project, profile, create-dir and external roots together,
    including disabled/platform gates and duplicate names. Keep the shared
    parsed cache for local metadata; parse extra roots with the same bounded
    per-file cache. Standalone plugin tests without Hermes retain local mode.
    """
    local = cached_catalog(skills_dir, cache)
    session_platform = os.environ.get("HERMES_PLATFORM") or os.environ.get("HERMES_SESSION_PLATFORM", "")
    if not session_platform:
        try:
            session_platform = importlib.import_module("gateway.session_context").get_session_env(
                "HERMES_SESSION_PLATFORM"
            ) or ""
        except (ImportError, AttributeError, OSError):
            pass
    # An independent, shared visibility snapshot avoids re-importing and
    # re-scanning the host's full skill catalog in every fresh Hermes process.
    # Root identity includes trusted project and external roots; the config
    # signature catches disabled/root changes between turns.
    roots: list[tuple[int, Path]] = [(1, skills_dir)]
    try:
        roots = importlib.import_module("agent.skill_utils").get_skill_search_roots(local=skills_dir)
    except ModuleNotFoundError as exc:
        if exc.name not in {"agent", "agent.skill_utils"}:
            return ()
    except (ImportError, AttributeError, OSError):
        return ()
    try:
        signature = [
            1,
            str(skills_dir),
            _mtime_ns(str(skills_dir.parent / "config.yaml")),
            session_platform,
            [[tier, _signature(Path(root)) if Path(root).is_dir() else [str(root), None]] for tier, root in roots],
        ]
    except OSError:
        return ()
    shared = cache.with_name("resolved-catalog.json")
    ttl = _visibility_ttl()
    previous: tuple[SkillRecord, ...] = ()
    same = False
    if ttl > 0:
        try:
            data = json.loads(shared.read_text(encoding="utf-8"))
            previous = tuple(SkillRecord(**{**item, "tags": tuple(item["tags"])}) for item in data["records"])
            same = data["signature"] == signature
            if same and 0 <= time.time() - data["ts"] < ttl:
                return previous
        except (OSError, ValueError, KeyError, TypeError):
            pass
    lock = shared.with_name(shared.name + ".lock")
    owner = False
    if ttl > 0:
        try:
            shared.parent.mkdir(parents=True, exist_ok=True)
            if lock.exists() and not 0 <= time.time() - lock.stat().st_mtime <= _LOCK_STALE_S:
                lock.unlink()
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL))
            owner = True
        except FileExistsError:
            if same:
                return previous
        except OSError:
            pass
    try:
        try:
            host_catalog = importlib.import_module("tools.skills_tool")._skill_catalog
        except ModuleNotFoundError as exc:
            return local if exc.name in {"tools", "tools.skills_tool"} else ()
        except (ImportError, AttributeError):
            return ()
        try:
            entries = host_catalog()
        except Exception:  # noqa: BLE001 -- an unavailable host index must fail closed
            return ()
        local_by_source = {item.source: item for item in local}
        resolved: dict[str, SkillRecord] = {}
        for entry in entries:
            load_name = entry.get("load_name")
            if not load_name or entry.get("status") == "shadowed":
                continue
            path = Path(entry["path"])
            source = str(path)
            parsed = local_by_source.get(source) or _parse_skill(path, Path(entry["root"]))
            if parsed is None:
                continue
            name = str(load_name)
            record = SkillRecord(
                name=name,
                category="" if "/" in name else str(entry.get("category") or parsed.category),
                description=str(entry.get("description") or parsed.description),
                tags=parsed.tags,
                source=source,
            )
            resolved.setdefault(record.canonical_name, record)
        result = tuple(resolved[key] for key in sorted(resolved))
        if owner:
            tmp = shared.with_name(f"{shared.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            with contextlib.suppress(OSError):
                tmp.write_text(json.dumps({"signature": signature, "ts": time.time(),
                                           "records": [asdict(item) for item in result]}), encoding="utf-8")
                os.replace(tmp, shared)
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return result
    finally:
        if owner:
            with contextlib.suppress(OSError):
                lock.unlink()
