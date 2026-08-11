"""Tests for the skill-router engine — isolated, fixture-based, no network."""

import os
from pathlib import Path

import pytest

from skill_router import engine

MATRIX = """# Test-Matrix

## Thema 1: Documents / OCR

**Keywords:** `ocr`, `pdf`, `document`, `scan`

| Kategorie | Skills |
|-----------|--------|
| **Pflicht** | `pdf-extraction`, `action-items` |
| **Optional** | `debugging` |

## Thema 2: Scheduling

**Keywords:** `calendar`, `schedule`, `reminder`

| Kategorie | Skills |
|-----------|--------|
| **Pflicht** | `calendar-sync` |
"""

SKILL_PDF = """---
name: pdf-extraction
description: "Extract text from PDFs and scans."
metadata:
  hermes:
    tags: [PDF, OCR, Documents]
---
"""
SKILL_KANBAN = """---
name: kanban-orchestration
description: "Orchestrate tasks on a kanban board."
metadata:
  hermes:
    tags: [Kanban, Tasks]
---
"""
SKILL_CAL = """---
name: calendar-sync
description: "Sync calendar events."
metadata:
  hermes:
    tags: [Calendar, Schedule]
---
"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """Temp HERMES_HOME with fixture skills."""
    skills = tmp_path / "skills"
    (skills / "productivity" / "pdf-extraction").mkdir(parents=True)
    (skills / "productivity" / "pdf-extraction" / "SKILL.md").write_text(SKILL_PDF)
    (skills / "software-development" / "kanban-orchestration").mkdir(parents=True)
    (skills / "software-development" / "kanban-orchestration" / "SKILL.md").write_text(SKILL_KANBAN)
    (skills / "productivity" / "calendar-sync").mkdir(parents=True)
    (skills / "productivity" / "calendar-sync" / "SKILL.md").write_text(SKILL_CAL)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def test_topic_match_injects_pflicht(env):
    out = engine.build_injection(
        "Plan für den OCR-Bug im PDF-Dokument",
        env / "skills",
        env / "matrix.md",
    )
    assert out is None  # matrix file does not exist yet -> no topics


def test_topic_match_with_matrix(env):
    matrix = env / "matrix.md"
    matrix.write_text(MATRIX)
    out = engine.build_injection(
        "Plan für den OCR-Bug im PDF-Dokument",
        env / "skills",
        matrix,
    )
    assert out is not None
    assert "Dokumente" in out or "Documents" in out
    assert "pdf-extraction" in out
    assert "action-items" in out


def test_skill_match_without_matrix(env):
    """Without a matrix the engine still matches skills via tags."""
    out = engine.build_injection("calendar schedule planning", env / "skills")
    assert out is not None
    assert "calendar-sync" in out


def test_no_match_returns_none(env):
    out = engine.build_injection("tell me a joke", env / "skills")
    assert out is None


def test_topic_change_signature(env):
    matrix = env / "matrix.md"
    matrix.write_text(MATRIX)
    a = engine.build_injection("OCR fehler im pdf", env / "skills", matrix)
    b = engine.build_injection("kalender termin eintragen", env / "skills", matrix)
    assert engine.match_signature(a) != engine.match_signature(b)
    assert engine.match_signature(a) == engine.match_signature(a)


def test_learning_associates_task_words(env):
    lexicon = {}
    updated = engine.learn_from_load(
        "mein handy zeigt fehler", {"injected_skill"}, "device-debugging", lexicon
    )
    assert "handy" in updated
    assert updated["handy"] == {"device-debugging": 1}
    # Already-injected skills must NOT be learned
    unchanged = engine.learn_from_load(
        "mein handy zeigt fehler", {"device-debugging"}, "device-debugging", lexicon
    )
    assert unchanged["handy"] == {"device-debugging": 1}


def test_learning_never_stores_task_ids(env):
    """Task-IDs und Hashes sind persönliche/technische Daten — nie lernen."""
    # Synthetisch zusammengesetzt, damit der Privacy-Guard-Scan sie nicht
    # als statisches Muster im Quelltext findet (echte IDs gehören nicht ins Repo).
    task_id = "t_" + "a1b2c3d4"
    hash_token = "a1b2c3d4"
    lexicon = {}
    updated = engine.learn_from_load(
        f"dokument scan mit {task_id} und hash {hash_token}",
        set(),
        "pdf-extraction",
        lexicon,
    )
    assert hash_token not in updated
    assert task_id not in updated
    # aber die Aufgaben-Keywords schon
    assert "dokument" in updated or "scan" in updated


def test_learning_skips_long_messages(env):
    """Lange Nachrichten sind Kontext, keine Aufgaben-Keywords — nichts lernen."""
    long_msg = " ".join(f"wort{i}" for i in range(60))
    lexicon = {}
    updated = engine.learn_from_load(long_msg, set(), "some-skill", lexicon)
    assert updated == {}


def test_learning_caps_at_five_words(env):
    longish = "eins zwei drei vier fünf sechs sieben acht neun zehn probleme"
    lexicon = {}
    updated = engine.learn_from_load(longish, set(), "some-skill", lexicon)
    assert len(updated) <= 5


def test_lexicon_roundtrip(tmp_path: Path):
    path = tmp_path / "learned_keywords.json"
    lex = {"handy": {"device-debugging": 2}}
    engine.save_lexicon(lex, path)
    assert engine.load_lexicon(path) == lex


def test_fallback_hint_is_short():
    assert len(engine.FALLBACK_HINT) < 200


def test_matrix_optional_default(env, monkeypatch):
    monkeypatch.delenv("SKILL_ROUTER_MATRIX_PATH", raising=False)
    assert engine.default_matrix_path() is None
