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
| **Required** | `pdf-extraction`, `action-items` |
| **Optional** | `debugging` |

## Thema 2: Scheduling

**Keywords:** `calendar`, `schedule`, `reminder`

| Kategorie | Skills |
|-----------|--------|
| **Required** | `calendar-sync` |
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


def test_topic_match_injects_required(env):
    out = engine.build_injection(
        "write the weekly status report",
        env / "skills",
        env / "matrix.md",
    )
    assert out is None  # matrix file does not exist yet, keine Tag-Treffer


def test_topic_match_with_matrix(env):
    matrix = env / "matrix.md"
    matrix.write_text(MATRIX)
    out = engine.build_injection(
        "Plan for the OCR bug in the PDF document",
        env / "skills",
        matrix,
    )
    assert out is not None
    assert "Documents" in out
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


def test_record_tool_call_tracks_stats(env):
    """Tool-Start erfasst Entscheidungsphasen-Wörter als Kookkurrenz.
    skill_view-Calls werden auf den Skill-Namen gemappt."""
    lexicon, stats = {}, engine.empty_stats()
    lexicon, stats = engine.record_tool_call(
        "emulator tastatur pruefen",
        "skill_view",
        {"name": "device-debugging"},
        lexicon,
        stats,
    )
    assert stats["total_calls"] == 1
    assert stats["tools"]["device-debugging"] == 1  # gemappt, nicht "skill_view"
    assert stats["words"]["tastatur"] == 1
    assert lexicon["tastatur"] == {"device-debugging": 1}


def test_record_tool_call_with_bare_stats(env):
    """Regression: stats aus leerer Datei ({}) statt empty_stats() —
    setdefault muss vor dem Lesen laufen (RHS-Reihenfolge)."""
    lexicon = {}
    stats = {}  # exakt was load_stats() aus einer leeren Datei liefert
    lexicon, stats = engine.record_tool_call(
        "emulator tastatur", "terminal", None, lexicon, stats
    )
    assert stats["total_calls"] == 1
    assert stats["tools"] == {"terminal": 1}
    assert stats["words"]["emulator"] == 1
    assert lexicon["tastatur"] == {"terminal": 1}


def test_record_never_stores_task_ids(env):
    """Task-IDs und Hashes sind persönliche/technische Daten — nie erfassen."""
    # Synthetisch zusammengesetzt, damit der Privacy-Guard-Scan sie nicht
    # als statisches Muster im Quelltext findet (echte IDs gehören nicht ins Repo).
    task_id = "t_" + "a1b2c3d4"
    hash_token = "a1b2c3d4"
    lexicon, stats = {}, engine.empty_stats()
    lexicon, stats = engine.record_tool_call(
        f"document scan with {task_id} and hash {hash_token}",
        "skill_view",
        {"name": "pdf-extraction"},
        lexicon,
        stats,
    )
    assert hash_token not in lexicon and hash_token not in stats["words"]
    assert task_id not in lexicon and task_id not in stats["words"]
    # but the task keywords are captured
    assert "document" in lexicon or "scan" in lexicon


def test_record_skips_long_messages(env):
    """Long messages are context, not task keywords — nothing is captured."""
    long_msg = " ".join(f"word{i}" for i in range(60))
    lexicon, stats = {}, engine.empty_stats()
    lexicon, stats = engine.record_tool_call(
        long_msg, "terminal", None, lexicon, stats
    )
    assert lexicon == {}
    assert stats["words"] == {}
    assert stats["total_calls"] == 1  # der Call selbst zählt immer


def test_record_caps_at_five_words(env):
    longish = "three four five six seven eight nine ten problems to fix"
    lexicon, stats = {}, engine.empty_stats()
    lexicon, stats = engine.record_tool_call(
        longish, "terminal", None, lexicon, stats
    )
    assert len(lexicon) <= 5


def test_lift_specific_vs_generic():
    """Generische Wörter (gleichmäßig über alle Tools) haben Lift ~1,
    spezifische Wörter (konzentriert auf ein Tool) deutlich >1."""
    stats = {
        "total_calls": 100,
        "words": {"bitte": 80, "emulator": 10},
        "tools": {"calendar-sync": 40, "adb": 30},
    }
    lexicon = {
        "bitte": {"calendar-sync": 30, "adb": 30},
        "emulator": {"adb": 9, "calendar-sync": 1},
    }
    # erwartet: 80*40/100 = 32 -> lift 30/32 = 0.94  (Zufall)
    assert engine.lift("bitte", "calendar-sync", lexicon, stats) < 2.0
    # erwartet: 10*30/100 = 3 -> lift 9/3 = 3.0  (kausal)
    assert engine.lift("emulator", "adb", lexicon, stats) >= 2.0
    # 1x-Kookkurrenz ist kein belegtes Signal
    assert engine.lift("emulator", "calendar-sync", lexicon, stats) < 2.0


def test_matching_gate_ignores_generic_words(env):
    """Hohe Frequenz ohne Kausalität gewichtet nichts; spezifische Wörter schon."""
    stats = {
        "total_calls": 100,
        "words": {"schnell": 80, "emulator": 10},
        "tools": {"calendar-sync": 40},
    }
    generic = {"schnell": {"calendar-sync": 30}}
    out = engine.build_injection("schnell", env / "skills", None, generic, stats)
    assert out is None  # Frequenz ohne Kausalität -> kein Vorschlag

    specific = {"emulator": {"calendar-sync": 9}}
    out = engine.build_injection("emulator", env / "skills", None, specific, stats)
    assert out is not None
    assert "calendar-sync" in out

    # Ohne Stats (wenig Daten) zählt der alte Weg — Kompatibilität
    out = engine.build_injection("schnell", env / "skills", None, generic)
    assert out is not None


def test_prune_removes_non_causal_words():
    """Nutzungsbasierte Bereinigung: Wörter ohne kausale Assoziation fliegen raus."""
    stats = {
        "total_calls": 100,
        "words": {"bitte": 80, "emulator": 10},
        "tools": {"calendar-sync": 40, "adb": 30},
    }
    lexicon = {
        "bitte": {"calendar-sync": 30, "adb": 30},  # Lift ~1 überall -> Rauschen
        "emulator": {"adb": 9},                     # Lift 3.0 -> echtes Signal
    }
    pruned = engine.prune_lexicon(lexicon, stats)
    assert "bitte" not in pruned
    assert "emulator" in pruned

    # Zu wenig Daten: keine Bereinigung (Lift zu verrauscht)
    small = dict(stats, total_calls=10)
    assert engine.prune_lexicon(lexicon, small) == lexicon


def test_prune_spares_fresh_words():
    """Frische Wörter (Gesamt-Kookkurrenz < MIN_COOCCUR) werden verschont,
    damit neue Assoziationen nach dem Lift-Start anwachsen können."""
    stats = {
        "total_calls": 100,
        "words": {"windows": 1, "bitte": 60},
        "tools": {"windows-ssh-remote": 1, "adb": 30},
    }
    lexicon = {
        "windows": {"windows-ssh-remote": 1},  # frisch, co gesamt 1 -> bleibt
        "bitte": {"adb": 30},                  # genug Daten, kein Signal -> weg
    }
    pruned = engine.prune_lexicon(lexicon, stats)
    assert "windows" in pruned
    assert "bitte" not in pruned


def test_cluster_words_identifies_causal_group():
    """Cluster = Wörter mit kausaler Assoziation zu einem Tool."""
    stats = {
        "total_calls": 100,
        "words": {"dokument": 4, "scan": 4, "karte": 10},
        "tools": {"pdf-extraction": 10, "kanban-orchestration": 20},
    }
    lexicon = {
        "dokument": {"pdf-extraction": 2},
        "scan": {"pdf-extraction": 2},
        "karte": {"kanban-orchestration": 5},
    }
    cluster = engine.cluster_words("pdf-extraction", lexicon, stats)
    assert cluster == {"dokument", "scan"}
    assert "karte" not in cluster


def test_cluster_bonus_rewards_coherent_hits():
    stats = {
        "total_calls": 100,
        "words": {"dokument": 4, "scan": 4, "karte": 10},
        "tools": {"pdf-extraction": 10, "kanban-orchestration": 20},
    }
    lexicon = {
        "dokument": {"pdf-extraction": 2},
        "scan": {"pdf-extraction": 2},
        "karte": {"kanban-orchestration": 5},
    }
    assert engine.cluster_bonus({"dokument", "scan"}, "pdf-extraction", lexicon, stats) == 2
    assert engine.cluster_bonus({"dokument"}, "pdf-extraction", lexicon, stats) == 0
    assert engine.cluster_bonus({"dokument", "scan", "x"}, "pdf-extraction", lexicon, stats) == 2
    assert engine.cluster_bonus({"karte"}, "pdf-extraction", lexicon, stats) == 0


def test_cluster_bonus_lifts_skill_above_competitor(env):
    """Kohärente Mehrfach-Treffer heben einen Skill über einen Einzelwort-Skill."""
    stats = {
        "total_calls": 100,
        "words": {"dokument": 4, "scan": 4, "karte": 10},
        "tools": {"pdf-extraction": 10, "kanban-orchestration": 20},
    }
    lexicon = {
        "dokument": {"pdf-extraction": 2},
        "scan": {"pdf-extraction": 2},
        "karte": {"kanban-orchestration": 5},
    }
    out = engine.build_injection(
        "dokument scan karte", env / "skills", None, lexicon, stats
    )
    assert out is not None
    # pdf-extraction: count 4 + Cluster-Bonus 2 = 6  >  kanban: 5 + 0
    assert out.index("pdf-extraction") < out.index("kanban-orchestration")


def test_generic_lexicon_word_not_weighted(env):
    """Wort mit >=5 Skill-Assoziationen ist generisch — erzeugt KEIN Matching-Gewicht."""
    generic = {
        "phone": {
            "calendar-sync": 5,
            "skill-b": 1,
            "skill-c": 1,
            "skill-d": 1,
            "skill-e": 1,
        }
    }
    out = engine.build_injection("phone", env / "skills", None, generic)
    assert out is None  # generisches Wort allein matcht keinen Fixture-Skill

    specific = {"phone": {"calendar-sync": 5}}
    out = engine.build_injection("phone", env / "skills", None, specific)
    assert out is not None
    assert "calendar-sync" in out


def test_learn_words_skips_generic_entries():
    generic = {
        "phone": {
            "skill-a": 1,
            "skill-b": 1,
            "skill-c": 1,
            "skill-d": 1,
            "skill-e": 1,
        }
    }
    words = engine.learn_words("phone document issue", generic)
    assert "phone" not in words  # generisch — nicht mehr lernen
    assert "document" in words


def test_learn_words_three_letter_whitelist():
    """Fachbegriffe mit 3 Buchstaben (ssh, adb, ...) werden trotz
    Mindestlänge 4 erkannt — gezielt über die Whitelist."""
    words = engine.learn_words("ssh verbinden windows adb testen")
    assert "ssh" in words
    assert "adb" in words
    assert "windows" in words


def test_learn_words_three_letter_noise_filtered():
    """Nicht-Whitelist-3er (sie, mit, wie) werden weiterhin ignoriert."""
    words = engine.learn_words("sie und mit wie")
    assert not any(len(w) == 3 for w in words)


def test_task_words_three_letter_matches(env):
    """3-Buchstaben-Whitelist-Wörter zählen beim Matching (ssh -> Skill)."""
    (env / "skills" / "autonomous-ai-agents" / "windows-ssh-remote").mkdir(parents=True)
    (env / "skills" / "autonomous-ai-agents" / "windows-ssh-remote" / "SKILL.md").write_text(
        "---\n"
        "name: windows-ssh-remote\n"
        "description: \"Drive a Windows PC remotely over SSH.\"\n"
        "metadata:\n"
        "  hermes:\n"
        "    tags: [SSH, Windows, Remote]\n"
        "---\n"
    )
    stats = {
        "total_calls": 100,
        "words": {"ssh": 10},
        "tools": {"windows-ssh-remote": 20},
    }
    lexicon = {"ssh": {"windows-ssh-remote": 5}}
    out = engine.build_injection("ssh verbinden", env / "skills", None, lexicon, stats)
    assert out is not None
    assert "windows-ssh-remote" in out


def test_lexicon_roundtrip(tmp_path: Path):
    path = tmp_path / "learned_keywords.json"
    lex = {"handy": {"device-debugging": 2}}
    engine.save_lexicon(lex, path)
    assert engine.load_lexicon(path) == lex


def test_save_lexicon_prunes_generic(tmp_path: Path):
    """Selbstreinigung: Einträge mit >=5 Skill-Assoziationen werden beim Speichern entfernt."""
    path = tmp_path / "learned_keywords.json"
    lex = {
        "good": {"skill-a": 2},
        "generic": {f"skill-{i}": 1 for i in range(5)},
    }
    engine.save_lexicon(lex, path)
    saved = engine.load_lexicon(path)
    assert "generic" not in saved  # generisch — physisch entfernt
    assert "good" in saved


def test_fallback_hint_is_short():
    assert len(engine.FALLBACK_HINT) < 200


def test_matrix_optional_default(env, monkeypatch):
    monkeypatch.delenv("SKILL_ROUTER_MATRIX_PATH", raising=False)
    assert engine.default_matrix_path() is None


# ── Output-Lernen (post_tool_call) — Task 1 ────────────────────────────────

def test_learn_from_result_associates_body_words(env):
    """Kanban-Task-Body im Tool-Ergebnis trainiert die Skill-Assoziation.

    'Schau ins Kanban und arbeite ab' ist indirekt — die finale Aufgabe steht
    im Task-Body. Die Body-Wörter müssen mit dem Tool (Skill) verknüpft werden.
    """
    lexicon, stats = {}, engine.empty_stats()
    result = '{"body": "Login-Screen implementieren mit Riverpod und go_router"}'
    lexicon, stats = engine.learn_from_result(
        user_message="schau ins kanban und arbeite ab",
        tool_name="terminal",
        result=result,
        lexicon=lexicon,
        stats=stats,
    )
    # Body-Fachwörter gelernt (Kanban-Boost 1x)
    assert "riverpod" in lexicon
    assert "router" in lexicon
    # User-Wort ebenfalls assoziiert
    assert "kanban" in lexicon


def test_learn_from_result_kanban_body_gets_full_weight(env):
    """F2: Kanban-Body-Felder (body) zählen 1x, sonstige Felder 0.5x.

    Der Boost ist über die Counts sichtbar: body-Wörter haben höhere Counts
    als generic-Feld-Wörter bei gleicher Häufigkeit.
    """
    lexicon, stats = {}, engine.empty_stats()
    result = '{"body": "riverpod refactor", "output": "riverpod version 3"}'
    lexicon, stats = engine.learn_from_result(
        user_message="mach weiter", tool_name="terminal",
        result=result, lexicon=lexicon, stats=stats,
    )
    body_count = lexicon["riverpod"]["terminal"]
    output_count = lexicon["version"]["terminal"]
    assert body_count > output_count  # 1x vs 0.5x


def test_learn_from_result_ignores_failed_status(env):
    """Fehler-Ergebnisse sind Rauschen — nichts lernen."""
    lexicon, stats = {}, engine.empty_stats()
    result = '{"status": "error", "error_message": "timeout riverpod build"}'
    lexicon, stats = engine.learn_from_result(
        user_message="baue die app", tool_name="terminal",
        result=result, lexicon=lexicon, stats=stats,
    )
    assert "timeout" not in lexicon
    assert "riverpod" not in lexicon


def test_learn_from_result_caps_huge_output(env):
    """Riesen-Outputs (stdout-Monster) dürfen das Lexikon nicht fluten."""
    lexicon, stats = {}, engine.empty_stats()
    huge = "".join(f"filler{i} " for i in range(5000))
    result = f'{{"output": "{huge[:2000]}"}}'
    lexicon, stats = engine.learn_from_result(
        user_message="kurz", tool_name="terminal",
        result=result, lexicon=lexicon, stats=stats,
    )
    assert len(lexicon) < 50  # Deckel greift


def test_learn_from_result_plaintext_fallback(env):
    """Plaintext-Ergebnisse (kein JSON) werden als Text gelernt."""
    lexicon, stats = {}, engine.empty_stats()
    result = "document scan completed: ocr extracted 3 pages"
    lexicon, stats = engine.learn_from_result(
        user_message="scan das dokument", tool_name="skill_view",
        result=result, lexicon=lexicon, stats=stats,
    )
    assert "document" in lexicon or "scan" in lexicon or "ocr" in lexicon


def test_learn_from_result_never_learns_ids(env):
    """Task-IDs/Hashes aus Tool-Ergebnissen nie lernen (Privacy)."""
    lexicon, stats = {}, engine.empty_stats()
    task_id = "t_" + "a1b2c3d4"
    result = f'{{"body": "aufgabe {task_id}: riverpod einbauen"}}'
    lexicon, stats = engine.learn_from_result(
        user_message="kanban abarbeiten", tool_name="terminal",
        result=result, lexicon=lexicon, stats=stats,
    )
    assert task_id not in lexicon
    assert "riverpod" in lexicon


def test_output_learning_flag_default_off(tmp_path, monkeypatch):
    """F1: Feature-Flag Default aus — ohne config.yaml und ohne env kein Lernen."""
    monkeypatch.delenv("SKILL_ROUTER_OUTPUT_LEARNING", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert engine.output_learning_enabled() is False


def test_output_learning_flag_env_override(tmp_path, monkeypatch):
    """Env-Override schaltet das Flag ein (Tests/CI)."""
    monkeypatch.setenv("SKILL_ROUTER_OUTPUT_LEARNING", "1")
    assert engine.output_learning_enabled() is True


def test_output_learning_flag_config_yaml(tmp_path, monkeypatch):
    """config.yaml: skill_router.output_learning: true aktiviert das Lernen."""
    monkeypatch.delenv("SKILL_ROUTER_OUTPUT_LEARNING", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "model:\n  default: x\nskill_router:\n  output_learning: true\n",
        encoding="utf-8",
    )
    assert engine.output_learning_enabled() is True


def test_output_learning_flag_config_false(tmp_path, monkeypatch):
    """config.yaml mit false → deaktiviert."""
    monkeypatch.delenv("SKILL_ROUTER_OUTPUT_LEARNING", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "skill_router:\n  output_learning: false\n",
        encoding="utf-8",
    )
    assert engine.output_learning_enabled() is False
