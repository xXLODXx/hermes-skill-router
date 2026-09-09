"""Task-to-skill evidence extraction for v2."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Evidence, SkillRecord

_STOP = {
    "aber", "auch", "bitte", "dass", "eine", "einen", "für", "from", "help",
    "how", "ist", "make", "need", "sind", "the", "this", "und", "use", "with",
    "wird", "will", "you", "your", "task", "skills", "skill", "please",
}
_WORD = re.compile(r"[a-zäöüß0-9][a-zäöüß0-9_-]{2,}", re.IGNORECASE)


def tokens(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text) if word.casefold() not in _STOP}


def _field_tokens(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        result.update(tokens(value.replace("-", " ")))
    return result


def evidence_for(message: str, skill: SkillRecord) -> tuple[Evidence, ...]:
    task = tokens(message)
    if not task:
        return ()
    result: list[Evidence] = []
    name_words = _field_tokens((skill.name,))
    tag_words = _field_tokens(skill.tags)
    desc_words = tokens(skill.description)
    for word in sorted(task & name_words):
        result.append(Evidence("name", word, 5.0, f"Skillname enthält '{word}'"))
    for word in sorted(task & tag_words):
        result.append(Evidence("tag", word, 3.0, f"Skill-Tag enthält '{word}'"))
    for word in sorted(task & desc_words):
        result.append(Evidence("description", word, 1.0, f"Beschreibung enthält '{word}'"))
    return tuple(result)
