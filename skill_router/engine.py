"""Skill-Router-Engine: aufgabenbasiertes, selbstlernendes Skill-Matching.

Generalisierte Engine (ohne Hermes-Plugin-Abhängigkeiten), damit sie isoliert
testbar ist und als eigenständiges Plugin-Paket angeboten werden kann.

Kernideen:
1.  Die User-Aufgabe wird gegen Themen-Keywords einer optionalen Routing-Matrix
    und gegen Tags/Description-Wörter aller installierten Skills gematcht.
2.  Injiziert wird nur der relevante Teil (Token-schonend); kein Match -> ein
    kurzer Hinweis, einmal pro Session.
3.  Themenwechsel in laufender Session werden erkannt (Match-Signatur).
4.  Selbstlernen: lädt das Modell einen Skill ausserhalb der Injektion, werden
    die Schlüsselwörter der Aufgabe dauerhaft mit dem Skill assoziiert.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# ── Konfiguration ────────────────────────────────────────────────────────────

# Optionale Routing-Matrix. Ohne Matrix arbeitet die Engine rein über
# Tag/Description-Matching — die Matrix ist ein reiner Qualitäts-Boost.
# Setzen: Umgebungsvariable SKILL_ROUTER_MATRIX_PATH oder DEFAULT_MATRIX_REL.
DEFAULT_MATRIX_REL: Path | None = None
MAX_EXTRA_SKILLS = 15
LEXICON_CAP = 400
GENERIC_SKILL_THRESHOLD = 5  # Wort mit >=5 Skill-Assoziationen = generisch: nicht lernen, nicht gewichten
LIFT_THRESHOLD = 2.0         # Kausalitäts-Gate: Kookkurrenz >= 2x ueber Zufallserwartung
MIN_COOCCUR = 2              # Minimum-Support: Assoziation zaehlt erst ab 2 Kookkurrenzen
MIN_CALLS_FOR_LIFT = 25      # ab so vielen Tool-Calls ist der Lift belastbar (vorher zu verrauscht)
CLUSTER_BONUS = 2            # Cluster-Treffer: +Punkte pro weiterem Wort eines Tool-Clusters (ab 2)

STOPWORDS = {
    "task", "tasks", "plan", "app", "apps", "tool", "tools", "skill", "skills",
    "use", "using", "used", "the", "and", "for", "with", "von", "und", "für",
    "der", "die", "das", "ein", "eine", "einen", "einem", "einer", "auf", "ist",
    "are", "was", "you", "your", "how", "what", "when", "where", "why", "will",
    "this", "that", "these", "those", "from", "have", "has", "had", "not",
    "can", "could", "should", "would", "about", "into", "over", "under", "than",
    "then", "them", "they", "their", "there", "here", "also", "only", "very",
    "just", "like", "make", "made", "want", "need", "help", "nice", "good",
    "gerne", "bitte", "danke", "sagen", "machen", "gehen", "kommen", "haben",
    "sein", "einer", "eines", "etwas", "immer", "noch", "schon", "auch", "aber",
    "hermes", "aufgaben", "aufgabe", "offene", "offen", "gibt", "gegen", "über",
    "nochmal", "gerade", "einfach", "vielleicht", "frage", "fragen", "diese",
    "diesen", "dieser", "soll", "sollte", "kannst", "können", "würde", "wird",
    "werden", "wurde", "wieder", "zurück", "darauf", "davor", "dazwischen",
    # Generic words that create noise as skill search terms
    # (skill matching only — matrix keywords stay unfiltered).
    "guidance", "preference", "gain", "standalone", "fixture", "below",
    "governs", "claims", "theirs", "against", "protected", "uninstalled",
    "confident", "statically", "modifications", "consolidation", "recommended",
    "meant", "boilerplate", "packaged", "verbosity", "frustration", "quoted",
    "retrying", "earliest", "kinds", "emerged", "three", "corrections", "tone",
    "merely", "handled", "scaffolding", "guessing", "either", "knowing",
    "generators", "ended", "missed", "authoritative", "attempts", "owned",
    "updating", "things", "limits", "existing", "territory", "invoke", "narrow",
    "constraint", "umbrella", "constraints", "installed", "notice", "fired",
    "external", "must", "actually", "small", "hate", "encode", "cites",
    "reproduce", "warrants", "belongs", "captures", "independently",
    "unconfigured", "fixed", "embedding", "narratives", "tried", "persistent",
    "content", "corrected", "pick", "verbose", "yours", "knowledge",
    "several", "might", "manually", "something", "subsection", "nothing",
    "runnable", "untested", "signal", "refusals", "prefer", "expressed",
    "runtime", "wrong", "probes", "outcome", "background", "string", "repeat",
    "directory", "concise", "extend", "remember", "worked", "outdated",
    "benefit", "validated", "handles", "unresolved", "technique", "starting",
    "codename", "explicit", "months", "updates", "denied", "wrote", "finding",
    "transcripts", "upstream", "imposed", "managed", "excerpts", "practice",
    "through", "complain", "foreground", "broken", "configs", "marked",
    "resolved", "shapes", "bite", "fits", "actor", "copied", "quirks",
    "situation", "itself", "produced", "never", "reply", "trust", "overlap",
    "default", "actual", "above", "give", "current", "asked", "broaden",
    "adopt", "currently", "shape", "detail", "includes", "actions", "without",
    "being", "play", "present", "pass", "starter", "even", "check", "hand",
    "note", "order", "scale", "type", "number", "state", "body", "post",
    "call", "work", "time", "support", "market", "rich", "end", "next", "look",
}


# ── Pfade ────────────────────────────────────────────────────────────────────

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def default_matrix_path(home: Path | None = None) -> Path | None:
    """Matrix-Pfad auflösen: env-Override gewinnt, sonst Default (falls gesetzt)."""
    env = os.environ.get("SKILL_ROUTER_MATRIX_PATH")
    if env:
        return Path(env)
    if DEFAULT_MATRIX_REL:
        return (home or hermes_home()) / DEFAULT_MATRIX_REL
    return None


# ── Persistenz: Lern-Lexikon ─────────────────────────────────────────────────

def load_lexicon(path: Path) -> dict:
    """{wort: {skill_name: count}} — gelernte Assoziationen laden."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_lexicon(lexicon: dict, path: Path) -> None:
    """Lexikon atomar persistieren; Selbstreinigung: generische Einträge
    (>= GENERIC_SKILL_THRESHOLD verschiedene Skills) entfernen, bei Cap die
    schwächsten Einträge trimmen."""
    lexicon = {
        w: v for w, v in lexicon.items() if len(v) < GENERIC_SKILL_THRESHOLD
    }
    if len(lexicon) > LEXICON_CAP:
        ranked = sorted(
            lexicon.items(), key=lambda kv: sum(kv[1].values()), reverse=True
        )
        lexicon = dict(ranked[:LEXICON_CAP])
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(lexicon, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


# ── Nutzungs-Statistik (Kausalitaets-Basis) ─────────────────────────────────

def empty_stats() -> dict:
    """{total_calls, words, tools} — Marginalien fuer die Lift-Berechnung."""
    return {"total_calls": 0, "words": {}, "tools": {}}


def load_stats(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return empty_stats()


def save_stats(stats: dict, path: Path) -> None:
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def record_tool_call(
    user_message: str,
    tool_name: str,
    args: dict | None,
    lexicon: dict,
    stats: dict,
) -> tuple[dict, dict]:
    """Tool-Start erfassen: Woerter der Entscheidungsphase (User-Message) mit dem
    gestarteten Tool assoziieren (Kookkurrenz). skill_view-Calls werden auf den
    Skill-Namen gemappt, damit das Matching-Ziel (Skill) getroffen wird."""
    stats["total_calls"] = stats.get("total_calls", 0) + 1
    target = tool_name
    if tool_name in ("skill_view", "view_skill", "skills_view"):
        target = (args or {}).get("name") or tool_name
    # Achtung: RHS wird vor dem setdefault ausgewertet — nie
    # `stats.setdefault(...)[k] = stats[k]...` (KeyError bei leerem stats).
    tools = stats.setdefault("tools", {})
    tools[target] = tools.get(target, 0) + 1
    for w in learn_words(user_message, lexicon):
        words = stats.setdefault("words", {})
        words[w] = words.get(w, 0) + 1
        entry = lexicon.setdefault(w, {})
        entry[target] = entry.get(target, 0) + 1
    return lexicon, stats


def lift(word: str, tool: str, lexicon: dict, stats: dict) -> float:
    """Kausalitaets-Mass: beobachtete Kookkurrenz / Zufallserwartung.
    ~1.0 = zufaellig (generisches Wort), deutlich >1 = spezifische Assoziation."""
    total = max(stats.get("total_calls", 0), 1)
    wc = stats.get("words", {}).get(word, 0)
    tc = stats.get("tools", {}).get(tool, 0)
    co = lexicon.get(word, {}).get(tool, 0)
    if co == 0 or wc == 0 or tc == 0:
        return 0.0
    expected = wc * tc / total
    return co / expected if expected > 0 else 0.0


def prune_lexicon(lexicon: dict, stats: dict) -> dict:
    """Nutzungsbasierte Bereinigung: Woerter ohne kausale Assoziation zu IRGENDEINEM
    Tool (bestes Lift < LIFT_THRESHOLD mit Minimum-Support) entfernen.
    Erst ab MIN_CALLS_FOR_LIFT — vorher ist der Lift zu verrauscht."""
    if stats.get("total_calls", 0) < MIN_CALLS_FOR_LIFT:
        return lexicon
    keep = {}
    for w, tools in lexicon.items():
        best = max(
            (lift(w, t, lexicon, stats) for t, c in tools.items() if c >= MIN_COOCCUR),
            default=0.0,
        )
        if best >= LIFT_THRESHOLD:
            keep[w] = tools
    return keep


def cluster_words(tool: str, lexicon: dict, stats: dict) -> set[str]:
    """Wort-Cluster eines Tools: Woerter mit kausaler Assoziation (Lift + Support).
    Das ist die Mindmap-Struktur: Ein Tool buendelt die Woerter, die es
    zuverlaessig vorhersagen."""
    return {
        w for w, assoc in lexicon.items()
        if assoc.get(tool, 0) >= MIN_COOCCUR
        and lift(w, tool, lexicon, stats) >= LIFT_THRESHOLD
    }


def cluster_bonus(words: set[str], tool: str, lexicon: dict, stats: dict) -> int:
    """Cluster-Treffer-Bonus: ab 2 Woertern eines Tool-Clusters in der Task
    +CLUSTER_BONUS je weiterem Treffer — kohaerentes Signal wiegt mehr als
    die Summe der Einzelcounts (Mindmap-Idee: zusammengehoerige Woerter
    verstaerken sich)."""
    hits = len(cluster_words(tool, lexicon, stats) & words)
    if hits >= 2:
        return (hits - 1) * CLUSTER_BONUS
    return 0


# ── Matrix parsen (optional) ─────────────────────────────────────────────────

def parse_matrix(text: str) -> list[dict]:
    """Themen mit Keywords + Pflicht/Optional-Skills aus der Matrix extrahieren."""
    topics = []
    lines = text.splitlines()
    current = None
    for line in lines:
        m = re.match(r"^## Thema \d+:\s*(.+)$", line.strip())
        if m:
            current = {"name": m.group(1).strip(), "keywords": [], "pflicht": [], "optional": []}
            topics.append(current)
            continue
        if current is None:
            continue
        km = re.match(r"^\*\*Keywords:\*\*\s*(.+)$", line.strip())
        if km:
            current["keywords"] = re.findall(r"`([^`]+)`", km.group(1))
            continue
        if "**Pflicht**" in line or "**Required**" in line:
            current["pflicht"] = re.findall(r"`([^`]+)`", line)
        elif "**Optional**" in line:
            current["optional"] = re.findall(r"`([^`]+)`", line)
    return topics


# ── Skill-Scan (live, mitwachsend) ───────────────────────────────────────────

def _desc_words(desc: str, limit: int = 20) -> set[str]:
    """Relevante Wörter der Skill-Description als zusätzliche Suchfläche."""
    words = set()
    for w in re.findall(r"[a-zäöüß]{4,}", desc.lower()):
        if w not in STOPWORDS and len(words) < limit:
            words.add(w)
    return words


def scan_skills(skills_dir: Path) -> list[dict]:
    """Alle installierten Skills: Kategorie, Name, Tags, Description-Wörter."""
    skills = []
    for cat_dir in sorted(skills_dir.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("."):
            continue
        for skill_dir in sorted(cat_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            md = skill_dir / "SKILL.md"
            if not md.exists():
                continue
            try:
                txt = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            m = re.search(r"^name:\s*[\"']?([^\"'\n]+)", txt, re.M)
            name = m.group(1).strip() if m else skill_dir.name
            tags = []
            m2 = re.search(r"hermes:\s*\n\s*tags:\s*\[([^\]]*)\]", txt)
            if m2:
                tags = [t.strip().strip("'\"") for t in m2.group(1).split(",")]
            else:
                m3 = re.search(r"^tags:\s*\[([^\]]*)\]", txt, re.M)
                if m3:
                    tags = [t.strip().strip("'\"") for t in m3.group(1).split(",")]
            m4 = re.search(r"^description:\s*[\"']?([^\"'\n]+)", txt, re.M)
            desc = m4.group(1).strip() if m4 else ""
            skills.append({
                "cat": cat_dir.name,
                "name": name,
                "tags": tags[:3],
                "desc_words": _desc_words(desc),
            })
    return skills


# ── Matching ─────────────────────────────────────────────────────────────────

def _norm_words(text: str) -> set[str]:
    return set(re.findall(r"[a-zäöüß0-9]+", text.lower()))


def _phrase_hits(text: str, keywords: list[str]) -> int:
    """Anzahl Keywords, die als Wort/Phrase in der Aufgabe vorkommen."""
    low = text.lower()
    hits = 0
    for kw in keywords:
        kw_l = kw.strip().lower()
        if not kw_l:
            continue
        if re.search(r"\b" + re.escape(kw_l) + r"\b", low):
            hits += 1
    return hits


def _task_words(user_message: str) -> set[str]:
    """Relevante Wörter der Aufgabe (für Matching)."""
    words = set()
    for w in re.findall(r"[a-zäöüß0-9]{4,}", user_message.lower()):
        if w not in STOPWORDS and re.search(r"[a-zäöüß]", w):
            words.add(w)
    return words


# ── Learning hardening (privacy) ─────────────────────────────────────────────

_ID_PATTERN = re.compile(r"^(?=.*\d)[a-z0-9]{8,}$")  # hashes/IDs (8+ alnum WITH digit); pure-letter words are vocabulary
_TASK_ID_PATTERN = re.compile(r"^t_[a-z0-9]+$")       # task IDs (t_<id>)
MAX_LEARN_WORDS = 5                                   # max keywords per learning event
MAX_LEARN_MESSAGE_WORDS = 40                          # longer messages = context, not learned


def learn_words(user_message: str, lexicon: dict | None = None) -> list[str]:
    """Task keywords for learning — in message order, hardened.

    - Only from SHORT messages (<= 40 words): long messages carry context
      or explanations, not concise task keywords.
    - IDs, hashes, task IDs (t_...) are never learned.
    - Words already associated with >= GENERIC_SKILL_THRESHOLD skills are
      skipped (generic vocabulary, e.g. from mass skill-load sessions).
    - At most 5 keywords per event (the first relevant ones).
    """
    if len(user_message.split()) > MAX_LEARN_MESSAGE_WORDS:
        return []
    result: list[str] = []
    for w in re.findall(r"[a-zäöüß0-9]{4,}", user_message.lower()):
        if w in STOPWORDS or not re.search(r"[a-zäöüß]", w):
            continue
        if _ID_PATTERN.match(w) or _TASK_ID_PATTERN.match(w):
            continue
        if lexicon:
            entry = lexicon.get(w)
            if entry and len(entry) >= GENERIC_SKILL_THRESHOLD:
                continue  # generisch — kein weiteres Lernen
        result.append(w)
        if len(result) >= MAX_LEARN_WORDS:
            break
    return result


def build_injection(
    user_message: str,
    skills_dir: Path,
    matrix_path: Path | None = None,
    lexicon: dict | None = None,
    stats: dict | None = None,
) -> str | None:
    """Injektion bauen: erkannte Matrix-Themen + passende Skills.

    Returns None, wenn weder Thema noch Skill matcht (Aufrufer entscheidet,
    ob der kurze Fallback-Hinweis injiziert wird).
    """
    topics: list[dict] = []
    if matrix_path is not None and matrix_path.exists():
        topics = parse_matrix(matrix_path.read_text(encoding="utf-8"))
    skills = scan_skills(skills_dir)
    lexicon = lexicon or {}

    # Themen matchen
    topic_hits = []
    for t in topics:
        score = _phrase_hits(user_message, t["keywords"])
        if score > 0:
            topic_hits.append((score, t))
    topic_hits.sort(key=lambda x: -x[0])

    # Skills matchen (Tags + Name + Kategorie + Description-Wörter + Lexikon)
    words = _task_words(user_message)
    routed = {s for t in topics for s in t["pflicht"] + t["optional"]}
    skill_hits = []
    for s in skills:
        if s["name"] in routed:
            continue  # schon über Matrix geroutet — keine Duplikate
        hay = set()
        for tag in s["tags"]:
            hay |= _norm_words(tag)
        hay |= _norm_words(s["name"])
        hay |= _norm_words(s["cat"])
        hay |= s["desc_words"]
        score = len((words - STOPWORDS) & hay)
        # Gelernte Assoziationen: count als Gewicht
        for w in words & set(lexicon):
            if len(lexicon[w]) >= GENERIC_SKILL_THRESHOLD:
                continue  # generisches Wort — kein Gewicht
            count = lexicon[w].get(s["name"], 0)
            if count == 0:
                continue
            if stats and stats.get("total_calls", 0) >= MIN_CALLS_FOR_LIFT:
                if count < MIN_COOCCUR or lift(w, s["name"], lexicon, stats) < LIFT_THRESHOLD:
                    continue  # Frequenz ohne Kausalitaet zaehlt nicht
            score += count
        if stats and stats.get("total_calls", 0) >= MIN_CALLS_FOR_LIFT:
            score += cluster_bonus(words, s["name"], lexicon, stats)
        if score > 0:
            skill_hits.append((score, s))
    skill_hits.sort(key=lambda x: (-x[0], x[1]["name"]))

    if not topic_hits and not skill_hits:
        return None

    parts = ["### Skill Routing (automatic, task-based)\n"]
    if topic_hits:
        parts.append("Matched topics:")
        for score, t in topic_hits:
            parts.append(f"- {t['name']} (Match {score})")
            if t["pflicht"]:
                parts.append(f"  Required: {', '.join(t['pflicht'])}")
            if t["optional"]:
                parts.append(f"  Optional: {', '.join(t['optional'])}")
    if skill_hits:
        parts.append("Suggested skills (not routed by matrix):")
        shown = skill_hits[:MAX_EXTRA_SKILLS]
        for score, s in shown:
            tag_str = f" [{', '.join(s['tags'])}]" if s["tags"] else ""
            parts.append(f"- {s['cat']}/{s['name']}{tag_str}")
        rest = len(skill_hits) - len(shown)
        if rest > 0:
            parts.append(f"- ... and {rest} more (check the skill index)")
    parts.append("Load matching skills with skill_view(name) and follow their instructions.")
    return "\n".join(parts)


FALLBACK_HINT = (
    "### Skill Routing (automatic)\n"
    "No topic matched this task. For complex tasks, load the workflow-router "
    "skill (routing matrix).\n"
)


def match_signature(injection: str | None) -> tuple:
    """Kompakte Signatur des injizierten Match-Sets (Themen + Skills)."""
    if not injection:
        return ()
    topics = tuple(sorted(re.findall(r"^- ([A-Za-zäöüÄÖÜ0-9 /-]+?) \(Match", injection, re.M)))
    skills = tuple(sorted(re.findall(r"-\s+(?:Pflicht|Required|Optional): ([^\n]+)", injection)))
    return topics + skills


# ── Lernen aus Tool-Nutzung ──────────────────────────────────────────────────
# `record_tool_call` (oben) ersetzt das fruehere Skill-Load-Lernen: Jeder
# Tool-Start (inkl. skill_view) erfasst die Woerter der Entscheidungsphase
# als Kookkurrenz — der Lift filtert generische Woerter (Kausalitaet).
