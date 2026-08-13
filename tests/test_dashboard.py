"""Dashboard-Datenfluss-Tests (Schritt 5): Status-Semantik + mtime-Cache.

Testet die Abgriffstellen der Visualisierung: word_status (eine Quelle für
Engine + Dashboard), die overview/decision-Endpunkte und die
Cache-Invalidierung (keine Neuberechnung bei unverändertem Zustand).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from skill_router import engine

# ── word_status (eine Quelle) ──────────────────────────────────────────────


def test_word_status_beobachtet_unter_schwelle() -> None:
    """Zu wenige Tool-Calls: Lift ist noch nicht belastbar -> beobachtet."""
    lexicon = {"riverpod": {"flutter-dev": 3}}
    stats = {"total_calls": 10, "words": {"riverpod": 5}, "tools": {"flutter-dev": 4}}
    assert engine.word_status("riverpod", lexicon, stats, "flutter-dev", 3.0, 3) == "beobachtet"


def test_word_status_kausal() -> None:
    """Lift >= Schwelle + Support + nicht generisch -> kausal."""
    lexicon = {"riverpod": {"flutter-dev": 4}}
    stats = {"total_calls": 30, "words": {"riverpod": 6}, "tools": {"flutter-dev": 10}}
    lv = engine.lift("riverpod", "flutter-dev", lexicon, stats)
    assert lv >= engine.LIFT_THRESHOLD
    assert engine.word_status("riverpod", lexicon, stats, "flutter-dev", lv, 4) == "kausal"


def test_word_status_generisch_zu_viele_skills() -> None:
    """Wort mit >= GENERIC_SKILL_THRESHOLD Skill-Assoziationen: generisch,
    auch wenn der beste Lift hoch ist (Anzeige darf nicht lügen)."""
    lexicon = {
        "kanban": {
            f"skill-{i}": 3 for i in range(engine.GENERIC_SKILL_THRESHOLD + 1)
        }
    }
    stats = {
        "total_calls": 40,
        "words": {"kanban": 30},
        "tools": {f"skill-{i}": 10 for i in range(engine.GENERIC_SKILL_THRESHOLD + 1)},
    }
    lv = engine.lift("kanban", "skill-0", lexicon, stats)
    assert engine.word_status("kanban", lexicon, stats, "skill-0", lv, 3) == "generisch"


def test_word_status_generisch_ohne_kausalitaet() -> None:
    """Kookkurrenz ohne Lift: generisch (wird beim Prune entfernt)."""
    lexicon = {"wort": {"skill-a": 3, "skill-b": 3}}
    stats = {"total_calls": 40, "words": {"wort": 30}, "tools": {"skill-a": 30, "skill-b": 30}}
    lv = engine.lift("wort", "skill-a", lexicon, stats)
    assert engine.word_status("wort", lexicon, stats, "skill-a", lv, 3) == "generisch"


# ── Dashboard-Endpunkte + Cache ────────────────────────────────────────────


@pytest.fixture
def dashboard_env(tmp_path: Path, monkeypatch) -> dict:
    """plugin_api gegen temporäre Datendateien richten."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "learned_keywords.json").write_text(
        json.dumps({"riverpod": {"flutter-dev": 4}, "kanban": {"kanban-skill": 2}}),
        encoding="utf-8",
    )
    (data_dir / "tool_stats.json").write_text(
        json.dumps({
            "total_calls": 30,
            "words": {"riverpod": 6, "kanban": 5},
            "tools": {"flutter-dev": 10, "kanban-skill": 5},
        }),
        encoding="utf-8",
    )
    # Mini-Skills-Verzeichnis für die dynamische Ergänzung (Option live):
    # zwei zusätzliche Skills ohne Lern-Daten + einer, der dem Fixture-
    # Tool entspricht (flutter-dev) — testet, dass alle erscheinen.
    skills_root = tmp_path / "skills"
    for cat, skills in {
        "software-development": ["flutter-dev", "kanban-skill"],
        "email": ["dummy-skill"],
    }.items():
        for s in skills:
            d = skills_root / cat / s
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(
                f"---\nname: {s}\ndescription: Test-Skill {s}\n---\n",
                encoding="utf-8",
            )
    import dashboard.plugin_api as api

    api._LEXICON_PATH = data_dir / "learned_keywords.json"
    api._STATS_PATH = data_dir / "tool_stats.json"
    # _PLUGIN_DIR ebenfalls isolieren — sonst schreiben die last_injection-
    # Tests in den ECHTEN Plugin-Clone (data/last_injection.json des Hooks
    # wird überschrieben/gelöscht; gefunden 2026-08-13).
    api._PLUGIN_DIR = tmp_path
    api._cache_mtime = None
    api._cache_overview = None
    api._cache_decision = None
    return api


def test_overview_liefert_status_und_marginalien(dashboard_env) -> None:
    api = dashboard_env
    result = api.overview()
    assert result["total_calls"] == 30
    assert result["lexicon_size"] == 2
    assert result["lift_active"] is True
    words = {w["wort"]: w for w in result["words"]}
    assert words["riverpod"]["status"] == "kausal"
    assert words["riverpod"]["top_tool"] == "flutter-dev"


def test_cache_wird_bei_aenderung_invalidiert(dashboard_env, tmp_path: Path) -> None:
    api = dashboard_env
    first = api.overview()
    assert api._cache_overview is not None
    # Zweiter Aufruf ohne Änderung: Cache wird genutzt (gleiche Objekt-ID)
    second = api.overview()
    assert second is first  # identisches Objekt = Cache-Hit
    # Daten ändern: mtime ändert sich -> Cache invalidiert -> neue Berechnung
    time.sleep(0.01)  # mtime-Auflösung
    (tmp_path / "data" / "tool_stats.json").write_text(
        json.dumps({
            "total_calls": 31,
            "words": {"riverpod": 6, "kanban": 5},
            "tools": {"flutter-dev": 10, "kanban-skill": 5},
        }),
        encoding="utf-8",
    )
    third = api.overview()
    assert third is not first  # neu berechnet
    assert third["total_calls"] == 31


def test_decision_liefert_kandidaten(dashboard_env) -> None:
    api = dashboard_env
    result = api.decision()
    assert len(result["candidates"]) >= 1
    flutter = next(c for c in result["candidates"] if c["tool"] == "flutter-dev")
    assert flutter["status"] == "kausal"
    pro_words = [p["word"] for p in flutter["pro"]]
    assert "riverpod" in pro_words


def test_clusters_liefert_alle_kausalen_cluster(dashboard_env) -> None:
    """Cluster-Ansicht: kausale Cluster + ALLE Skills dynamisch ergänzt."""
    api = dashboard_env
    result = api.clusters()
    assert result["total_calls"] == 30
    # Fixture: riverpod->flutter-dev (co=4, Lift>2) UND kanban->kanban-skill
    # (co=2, Lift=2.4) sind beide kausal -> beide Cluster erscheinen.
    tools = [c["tool"] for c in result["clusters"]]
    assert "flutter-dev" in tools
    assert "kanban-skill" in tools  # co=2 + Lift 2.4 >= Schwelle -> kausal
    flutter = next(c for c in result["clusters"] if c["tool"] == "flutter-dev")
    assert flutter["count"] == 1
    assert flutter["words"][0]["word"] == "riverpod"
    assert flutter["words"][0]["status"] == "kausal"
    assert flutter["words"][0]["lift"] >= 2.0
    # Dynamische Ergänzung: alle installierten Skills sind enthalten
    # (kausale zuerst, dann die ohne Lern-Daten mit count=0)
    assert len(result["clusters"]) == result["total_skills"]
    assert result["total_skills"] == 3  # 3 Mini-Skills im Fixture
    empty = [c for c in result["clusters"] if c["count"] == 0]
    assert len(empty) == 1  # dummy-skill ohne Lern-Daten ist dabei
    assert empty[0]["tool"] == "dummy-skill"
    assert empty[0]["words"] == []
    # Meta-Wörter: JEDER Skill zeigt seine eigenen Wörter (Tags/Name/
    # Description) — auch ohne Lern-Daten sofort Inhalt.
    assert empty[0]["meta_words"] != []
    assert "dummy-skill" in empty[0]["meta_words"]
    flutter_row = next(c for c in result["clusters"] if c["tool"] == "flutter-dev")
    assert flutter_row["meta_words"] != []  # gelernt UND eigene Wörter


def test_last_injection_ohne_datei(dashboard_env) -> None:
    """Ohne last_injection.json: sauberer Leer-Zustand, kein Fehler."""
    api = dashboard_env
    result = api.last_injection()
    assert result["exists"] is False
    assert result["skills"] == []


def test_last_injection_mit_datei(dashboard_env, tmp_path) -> None:
    """Mit Datei: Task + Topics + Skills werden geliefert."""
    import dashboard.plugin_api as api_mod
    inj = api_mod._PLUGIN_DIR / "data" / "last_injection.json"
    inj.parent.mkdir(parents=True, exist_ok=True)
    inj.write_text(
        '{"ts": 1750000000, "message": "schau ins kanban", '
        '"topics": ["kanban"], "skills": ["kanban-dev-orchestration"]}',
        encoding="utf-8",
    )
    try:
        result = api_mod.last_injection()
        assert result["exists"] is True
        assert result["message"] == "schau ins kanban"
        assert result["topics"] == ["kanban"]
        assert result["skills"] == ["kanban-dev-orchestration"]
    finally:
        inj.unlink(missing_ok=True)
