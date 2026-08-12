"""Skill-Router Dashboard-Plugin — Backend-API.

Mounted at /api/plugins/workflow-router-autoload/ by the dashboard plugin
system (auth via the dashboard session token, like all core API routes).

Liest die beiden Lern-Dateien des Plugins (learned_keywords.json =
Wort→Tool-Kookkurrenz, tool_stats.json = Marginalien) und berechnet daraus
den Kausalitäts-Status jedes Wortes (Lift vs. Zufallserwartung) — dieselbe
Logik wie die Engine (skill_router/engine.py), hier bewusst als kleine
Duplikation für die read-only Anzeige.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter()

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
# Daten liegen zentral im Plugin-Datenordner (data/) — dieselben Pfade wie
# die Engine (skill_router/__init__.py). D2-Fix: vorher las das Dashboard
# aus dem Root und zeigte bei Repo-Installation immer leere Daten.
_LEXICON_PATH = _PLUGIN_DIR / "data" / "learned_keywords.json"
_STATS_PATH = _PLUGIN_DIR / "data" / "tool_stats.json"

# Konsistent mit engine.py — dupliziert für die Anzeige.
_LIFT_THRESHOLD = 2.0
_MIN_COOCCUR = 2
_MIN_CALLS_FOR_LIFT = 25


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _lift(word: str, tool: str, lexicon: dict, stats: dict) -> float:
    """Kausalitäts-Maß: beobachtete Kookkurrenz / Zufallserwartung."""
    total = max(stats.get("total_calls", 0), 1)
    wc = stats.get("words", {}).get(word, 0)
    tc = stats.get("tools", {}).get(tool, 0)
    co = lexicon.get(word, {}).get(tool, 0)
    if co == 0 or wc == 0 or tc == 0:
        return 0.0
    expected = wc * tc / total
    return co / expected if expected > 0 else 0.0


def _word_status(lift_value: float, co: int, total_calls: int) -> str:
    """kausal | generisch | beobachtet — je nach Lift, Support und Datenlage."""
    if total_calls >= _MIN_CALLS_FOR_LIFT:
        if co >= _MIN_COOCCUR and lift_value >= _LIFT_THRESHOLD:
            return "kausal"
        if co >= _MIN_COOCCUR:
            return "generisch"  # beim nächsten Prune entfernt
    return "beobachtet"  # zu wenige Daten oder 1x-Zufall


@router.get("/overview")
def overview() -> dict:
    """Kompakter Gesamtzustand: Marginalien + Wort-Tabelle mit Status."""
    lexicon = _load_json(_LEXICON_PATH)
    stats = _load_json(_STATS_PATH)
    total_calls = stats.get("total_calls", 0)

    rows = []
    for w, assoc in lexicon.items():
        best_tool, best_lift, best_co = "", 0.0, 0
        for t, co in assoc.items():
            lv = _lift(w, t, lexicon, stats)
            if lv > best_lift:
                best_tool, best_lift, best_co = t, lv, co
        rows.append({
            "wort": w,
            "status": _word_status(best_lift, best_co, total_calls),
            "lift": round(best_lift, 2),
            "count": sum(assoc.values()),
            "top_tool": best_tool,
            "tools": len(assoc),
        })
    rows.sort(key=lambda r: (-(r["status"] == "kausal"), -r["lift"]))

    return {
        "total_calls": total_calls,
        "lexicon_size": len(lexicon),
        "words_tracked": len(stats.get("words", {})),
        "tools_tracked": len(stats.get("tools", {})),
        "lift_active": total_calls >= _MIN_CALLS_FOR_LIFT,
        "top_tools": sorted(
            stats.get("tools", {}).items(), key=lambda kv: -kv[1]
        )[:12],
        "words": rows[:200],
    }


@router.get("/decision")
def decision() -> dict:
    """Entscheidungs-Mindmap: Task -> Skill-Kandidaten mit Pro/Contra.

    Zeigt die Funktionsweise des Kausalitäts-Matchings: Welche Skills sind
    Kandidaten, welche Wörter sprechen dafür (Pro = kausal, Lift >= Schwelle)
    und welche dagegen (Contra = Kookkurrenz ohne Kausalität, wird bereinigt).
    """
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
            lv = _lift(w, t, lexicon, stats)
            item = {"word": w, "count": co, "lift": round(lv, 2)}
            if co >= _MIN_COOCCUR and lv >= _LIFT_THRESHOLD:
                pro.append(item)
            else:
                contra.append(item)  # 1x-Zufall oder unter der Lift-Schwelle
            if (
                total_calls >= _MIN_CALLS_FOR_LIFT
                and co >= _MIN_COOCCUR
                and lv < _LIFT_THRESHOLD
            ):
                generic_words += 1
        pro.sort(key=lambda i: -i["lift"])
        contra.sort(key=lambda i: -i["count"])

        if total_calls < _MIN_CALLS_FOR_LIFT:
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

    return {
        "total_calls": total_calls,
        "generic_words": generic_words,
        "candidates": candidates,
    }
