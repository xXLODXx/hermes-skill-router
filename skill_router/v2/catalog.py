"""Deterministic installed-skill catalog for v2."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .models import SkillRecord

_FRONT = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_NAME = re.compile(r"^name:\s*[\"']?([^\"'\n]+?)[\"']?\s*$", re.MULTILINE)
_DESC = re.compile(r"^description:\s*[\"']?(.*?)[\"']?\s*$", re.MULTILINE)
_TAGS = re.compile(r"tags:\s*\[([^\]]*)\]", re.MULTILINE)


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


def scan_catalog(skills_dir: Path) -> tuple[SkillRecord, ...]:
    records: dict[str, SkillRecord] = {}
    if not skills_dir.is_dir():
        return ()
    paths = [Path(root) / filename for root, _, filenames in os.walk(skills_dir, followlinks=True) for filename in filenames if filename == "SKILL.md"]
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        front = _FRONT.search(text)
        metadata = front.group(1) if front else text[:2000]
        name = _field(metadata, _NAME) or path.parent.name
        name = name.strip()
        if not name or name.casefold() in records:
            continue
        category = path.parent.parent.name if path.parent.parent != skills_dir else ""
        records[name.casefold()] = SkillRecord(
            name=name,
            category=category,
            description=_field(metadata, _DESC),
            tags=_tags(metadata),
            source=str(path),
        )
    return tuple(records[key] for key in sorted(records))
