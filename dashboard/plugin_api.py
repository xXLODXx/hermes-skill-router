"""Skill-Router Dashboard-Plugin — Backend-API.

Mounted at /api/plugins/skill-router/ by the dashboard plugin
system (auth via the dashboard session token, like all core API routes).

Liest die beiden Lern-Dateien des Plugins (learned_keywords.json =
Wort→Tool-Kookkurrenz, tool_stats.json = Marginalien) und berechnet daraus
den Kausalitäts-Status jedes Wortes (Lift vs. Zufallserwartung).

Seit Schritt 5 (Review-Plan): Die Lift-/Status-Logik kommt aus
``skill_router.engine`` (eine Quelle — kein Drift mehr durch Duplikation).
Ein mtime-basierter Cache verhindert Neuberechnung pro Request bei
unverändertem Zustand (Overhead ≈ 0).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from fastapi import APIRouter

# Der Web-Server lädt plugin_api.py als ISOLIERTES Modul (spec_from_file_location)
# — das Plugin-Verzeichnis ist dabei NICHT im sys.path. Ohne diesen Eintrag
# schlägt der skill_router-Import fehl und die API-Routen werden nie gemountet
# (404 im Dashboard). Das Plugin-Verzeichnis muss sich selbst bekannt machen.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# Eine Quelle für Lift/Schwellen/Status — D3-Fix: keine Duplikation mehr.
from skill_router import engine
from skill_router.engine import (
    LIFT_THRESHOLD,
    MIN_CALLS_FOR_LIFT,
    MIN_COOCCUR,
    lift,
    word_status,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Daten liegen zentral im Plugin-Datenordner (data/) — dieselben Pfade wie
# die Engine (skill_router/__init__.py). D2-Fix: vorher las das Dashboard
# aus dem Root und zeigte bei Repo-Installation immer leere Daten.
_LEXICON_PATH = _PLUGIN_DIR / "data" / "learned_keywords.json"
_STATS_PATH = _PLUGIN_DIR / "data" / "tool_stats.json"

# mtime-Cache: nur bei Datei-Änderung neu berechnen (Overhead ≈ 0).
_cache_mtime: tuple[float, float] | None = None
_cache_overview: dict | None = None
_cache_decision: dict | None = None


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _data_mtime() -> tuple[float, float] | None:
    """mtime-Paar der beiden Datendateien (None wenn nicht vorhanden)."""
    try:
        return (_LEXICON_PATH.stat().st_mtime, _STATS_PATH.stat().st_mtime)
    except OSError:
        return None


def _invalidate_if_changed() -> None:
    """Cache invalidieren, wenn sich die Datendateien geändert haben."""
    global _cache_mtime, _cache_overview, _cache_decision
    mtime = _data_mtime()
    if mtime != _cache_mtime:
        _cache_mtime = mtime
        _cache_overview = None
        _cache_decision = None


@router.get("/overview")
def overview() -> dict:
    """Kompakter Gesamtzustand: Marginalien + Wort-Tabelle mit Status."""
    global _cache_overview
    _invalidate_if_changed()
    if _cache_overview is not None:
        return _cache_overview
    lexicon = _load_json(_LEXICON_PATH)
    stats = _load_json(_STATS_PATH)
    total_calls = stats.get("total_calls", 0)

    rows = []
    for w, assoc in lexicon.items():
        best_tool, best_lift, best_co = "", 0.0, 0
        for t, co in assoc.items():
            lv = lift(w, t, lexicon, stats)
            if lv > best_lift:
                best_tool, best_lift, best_co = t, lv, co
        rows.append({
            "wort": w,
            "status": word_status(w, lexicon, stats, best_tool, best_lift, best_co),
            "lift": round(best_lift, 2),
            "count": sum(assoc.values()),
            "top_tool": best_tool,
            "tools": len(assoc),
        })
    rows.sort(key=lambda r: (-(r["status"] == "kausal"), -r["lift"]))

    result = {
        "total_calls": total_calls,
        "lexicon_size": len(lexicon),
        "words_tracked": len(stats.get("words", {})),
        "tools_tracked": len(stats.get("tools", {})),
        "lift_active": total_calls >= MIN_CALLS_FOR_LIFT,
        "top_tools": sorted(
            stats.get("tools", {}).items(), key=lambda kv: -kv[1]
        )[:12],
        "words": rows[:200],
    }
    _cache_overview = result
    return result


@router.get("/decision")
def decision() -> dict:
    """Entscheidungs-Mindmap: Task -> Skill-Kandidaten mit Pro/Contra.

    Zeigt den LERN-Zustand: Welche Skills die meisten Kookkurrenzen haben,
    welche Wörter dafür sprechen (Pro = kausal, Lift >= Schwelle) und welche
    dagegen (Contra = Kookkurrenz ohne Kausalität, wird bereinigt).
    """
    global _cache_decision
    _invalidate_if_changed()
    if _cache_decision is not None:
        return _cache_decision
    lexicon = _load_json(_LEXICON_PATH)
    stats = _load_json(_STATS_PATH)
    total_calls = stats.get("total_calls", 0)

    tool_counts: dict = {}
    for w, assoc in lexicon.items():
        for t, co in assoc.items():
            tool_counts[t] = tool_counts.get(t, 0) + co

    candidates = []
    generic_words = 0
    for t in sorted(tool_counts, key=lambda t: -tool_counts[t])[:6]:
        pro, contra = [], []
        for w, assoc in lexicon.items():
            co = assoc.get(t, 0)
            if co == 0:
                continue
            lv = lift(w, t, lexicon, stats)
            item = {"word": w, "count": co, "lift": round(lv, 2)}
            if word_status(w, lexicon, stats, t, lv, co) == "kausal":
                pro.append(item)
            else:
                contra.append(item)  # 1x-Zufall oder unter der Lift-Schwelle
            if (
                total_calls >= MIN_CALLS_FOR_LIFT
                and co >= MIN_COOCCUR
                and lv < LIFT_THRESHOLD
            ):
                generic_words += 1
        pro.sort(key=lambda i: -i["lift"])
        contra.sort(key=lambda i: -i["count"])

        if total_calls < MIN_CALLS_FOR_LIFT:
            status = "beobachtet"  # zu wenige Daten — Lift noch nicht belastbar
        elif pro:
            status = "kausal"
        elif contra:
            status = "generisch"  # Kookkurrenz ohne Kausalität -> bereinigt
        else:
            status = "beobachtet"

        candidates.append({
            "tool": t,
            "count": tool_counts[t],
            "status": status,
            "pro": pro[:4],
            "contra": contra[:4],
        })

    result = {
        "total_calls": total_calls,
        "generic_words": generic_words,
        "candidates": candidates,
    }
    _cache_decision = result
    return result


@router.get("/clusters")
def clusters() -> dict:
    """Cluster-Ansicht: ALLE Skills, dynamisch ergänzt.

    Zeile pro Skill: Skills mit kausalen Assoziationen zuerst (Wörter mit
    Status 'kausal', sortiert nach Cluster-Größe), danach alle übrigen
    installierten Skills ohne Lern-Daten (leere Zeile, erscheint nach
    erster Nutzung). Kein Top-N-Limit — neue Skills tauchen automatisch
    auf, sobald sie im System existieren.
    """
    _invalidate_if_changed()
    lexicon = _load_json(_LEXICON_PATH)
    stats = _load_json(_STATS_PATH)

    rows = []
    seen: set[str] = set()
    for t, assoc in _cluster_items(lexicon, stats):
        seen.add(t)
        words = []
        for w, co in assoc:
            lv = lift(w, t, lexicon, stats)
            words.append({
                "word": w,
                "lift": round(lv, 2),
                "count": co,
                "status": word_status(w, lexicon, stats, t, lv, co),
            })
        words.sort(key=lambda i: -i["lift"])
        rows.append({
            "tool": t,
            "count": len(words),
            "words": words[:12],  # Chips pro Zeile begrenzt, Rest via +N
            "more": max(len(words) - 12, 0),
        })

    # Alle übrigen installierten Skills ergänzen (noch ohne kausale Daten)
    try:
        all_skills = engine.scan_skills(engine.hermes_home() / "skills")
    except OSError:
        all_skills = []
    for s in all_skills:
        if s["name"] in seen:
            continue
        rows.append({
            "tool": s["name"],
            "count": 0,
            "words": [],
            "more": 0,
        })

    return {
        "total_calls": stats.get("total_calls", 0),
        "total_skills": len(all_skills),
        "clusters": rows,
    }


@router.get("/last-injection")
def last_injection() -> dict:
    """Letzte reale Skill-Injektion (Task -> Skills), vom Hook persistiert.

    Zeigt, was der Router ZULETZT tatsächlich in eine Session injiziert
    hat (Task-Wörter, Matched Topics, Skill-Pfade) — die lebendige
    Momentaufnahme statt der statischen Top-Kandidaten der Mindmap.
    """
    path = _PLUGIN_DIR / "data" / "last_injection.json"
    if not path.is_file():
        return {"exists": False, "ts": None, "message": None, "topics": [], "skills": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": False, "ts": None, "message": None, "topics": [], "skills": []}
    return {
        "exists": True,
        "ts": data.get("ts"),
        "message": data.get("message"),
        "topics": data.get("topics", []),
        "skills": data.get("skills", []),
    }


def _cluster_items(
    lexicon: dict, stats: dict
) -> list[tuple[str, list[tuple[str, int]]]]:
    """Alle (Tool, kausal assoziierte Wörter)-Paare, sortiert nach Cluster-Größe.

    Es zählen NUR Wörter mit Status 'kausal' — generische Wörter (>= 5
    Skill-Assoziationen oder Lift < Schwelle) sind keine Signale und
    verfälschen die Cluster-Ansicht.
    """
    clusters_map: dict[str, list[tuple[str, int]]] = {}
    for w, assoc in lexicon.items():
        for t, co in assoc.items():
            if co < MIN_COOCCUR:
                continue
            lv = lift(w, t, lexicon, stats)
            if (
                lv >= LIFT_THRESHOLD
                and word_status(w, lexicon, stats, t, lv, co) == "kausal"
            ):
                clusters_map.setdefault(t, []).append((w, co))
    return sorted(
        clusters_map.items(), key=lambda kv: -len(kv[1])
    )
