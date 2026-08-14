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

# Kurze Fachbegriffe (3 Buchstaben), die trotz Mindestlaenge 4 erkannt werden
# sollen — gezielt, damit kein Rausch-Schwall durchrutscht.
THREE_LETTER_WORDS = frozenset({
    "ssh", "ocr", "pdf", "tap", "adb", "avd", "ime", "api", "llm",
    "gpu", "cpu", "ram", "vm", "ui", "dns", "tls", "cli", "sdk",
})

# ── Output-Lernen (post_tool_call / post_llm_call) ──────────────────────────
# Tool-Ergebnisse und LLM-Antworten sind FOLGE-Signale: Sie werden nur als
# Lern-Eingaben verwendet (assoziiert mit der User-Message, die sie auslöste),
# nie als Direkt-Match der aktuellen Injektion. Feature-Flag output_learning
# (config.yaml, Default AN seit 2026-08-13, Freigabe nach Beobachtung) schaltet die
# Quellen frei; explizites `false` in config.yaml schaltet aus.
# Whitelist bewusst NUR Aufgaben-Felder: body (Task-Body) + description —
# output/text/result/summary enthalten Status-Felder und System-Meldungen
# (pending/completed/wurdest/capacity...), die nie User-Suchbegriffe sind
# (Option A der Wortqualitäts-Analyse 2026-08-12).
RESULT_TEXT_FIELDS = frozenset({
    "body", "description",
})
RESULT_BOOST_FIELDS = frozenset({"body"})  # F2: Kanban-Task-Body 1x-Gewicht
RESULT_MAX_CHARS = 500          # Größen-Deckel je Feld
RESULT_IGNORE_STATUSES = frozenset({"error", "failed", "cancelled"})
RESULT_WORD_WEIGHT = 1          # Folge-Signal: 0.5x entspricht Count +1
RESULT_BOOST_WEIGHT = 2         # Kanban-Body (1x): doppeltes Gewicht
MAX_RESULT_WORDS = 12           # max. gelernte Wörter je Tool-Ergebnis

# Woerter >= 4 Zeichen ODER Whitelist-3er als ganze Woerter (Reihenfolge erhalten).
_WORD_PATTERN = re.compile(
    r"[a-zäöüß0-9]{4,}"
    r"|(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in sorted(THREE_LETTER_WORDS)) + r")(?![a-z0-9])"
)

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
    "sein", "eines", "etwas", "immer", "noch", "schon", "auch", "aber",
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


# ── Feature-Flag: Output-Lernen (F1) ─────────────────────────────────────────
# config.yaml: skill_router.output_learning (Default AN seit 2026-08-13,
# Freigabe nach Beobachtung — das Lernen aus Tool-Ergebnissen ist die
# Grundlage für kausale Wort-Chips ALLER Skills, nicht nur der User-Wörter).
# Explizites `output_learning: false` in config.yaml schaltet aus.
# Env-Override SKILL_ROUTER_OUTPUT_LEARNING für Tests/CI (gewinnt immer).

def output_learning_enabled() -> bool:
    """True, wenn das Output-Lernen (post_tool_call/post_llm_call) aktiv ist.

    Default ist AN (seit 2026-08-13): ohne config.yaml, ohne env und ohne
    expliziten Config-Eintrag wird gelernt. Ein explizites
    ``output_learning: false`` in config.yaml (oder env ``0``/``false``)
    schaltet das Lernen aus.
    """
    env = os.environ.get("SKILL_ROUTER_OUTPUT_LEARNING")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    try:
        config_path = hermes_home() / "config.yaml"
        if not config_path.is_file():
            return True
        text = config_path.read_text(encoding="utf-8")
        # Schlankes YAML-Scannen ohne PyYAML-Abhängigkeit in der Engine:
        # skill_router: … output_learning: true
        m = re.search(
            r"skill_router\s*:\s*\n(?:[ \t].*\n)*?[ \t]+output_learning\s*:\s*(\S+)",
            text,
        )
        if not m:
            return True
        return m.group(1).strip().lower() in {"true", "yes", "on", "1"}
    except OSError:
        return True


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
    df_generic: set[str] | None = None,
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
    for w in learn_words(user_message, lexicon, df_generic):
        words = stats.setdefault("words", {})
        words[w] = words.get(w, 0) + 1
        entry = lexicon.setdefault(w, {})
        entry[target] = entry.get(target, 0) + 1
    return lexicon, stats


def _result_text_fields(result: object) -> list[tuple[str, str]]:
    """Text-Felder eines Tool-Ergebnisses defensiv extrahieren.

    JSON-Objekte (dict ODER JSON-String): nur Felder aus RESULT_TEXT_FIELDS,
    je Feld auf RESULT_MAX_CHARS gekürzt. Plaintext/Listen: als Ganzes
    behandeln. Fehler-Status (RESULT_IGNORE_STATUSES) → leere Liste
    (Rauschen).
    """
    if result is None:
        return []
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                result = parsed
    if isinstance(result, dict):
        status = str(result.get("status", "") or "").casefold()
        if status in RESULT_IGNORE_STATUSES:
            return []
        fields = []
        for key in RESULT_TEXT_FIELDS:
            value = result.get(key)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                value = " ".join(str(v) for v in value)
            if not isinstance(value, str):
                value = str(value)
            if value.strip():
                fields.append((key, value[:RESULT_MAX_CHARS]))
        return fields
    if isinstance(result, (list, tuple)):
        # Plaintext/Listen = Output/Rauschen: KEINE Lern-Felder (Option A)
        return []
    # Plaintext = Terminal-Ausgaben/System-Meldungen: keine Lern-Signale
    return []


def _lexicon_add(
    lexicon: dict, stats: dict, target: str, words: list[str], weight: int
) -> None:
    """Wörter mit Gewicht assoziieren (weight = ganzzahlige Zähler)."""
    for w in words:
        stats.setdefault("words", {})[w] = stats.get("words", {}).get(w, 0) + 1
        entry = lexicon.setdefault(w, {})
        entry[target] = entry.get(target, 0) + weight


def learn_from_result(
    user_message: str,
    tool_name: str,
    result: object,
    lexicon: dict,
    stats: dict,
    args: dict | None = None,
    df_generic: set[str] | None = None,
) -> tuple[dict, dict]:
    """Tool-Ergebnis (post_tool_call) als Lern-Eingabe verwenden.

    Löst die Indirektions-Lücke: 'Schau ins Kanban und arbeite ab' — die
    finale Aufgabe steht im Tool-Ergebnis (Task-Body). Die Wörter des
    Ergebnisses werden mit dem Tool/Skill assoziiert, das sie lieferte.
    skill_view-Calls werden auf den Skill-Namen gemappt (args['name']),
    damit das Matching-Ziel (Skill) getroffen wird — konsistent mit
    record_tool_call.

    Gewichtung (F2): Kanban-Body-Felder (``body``) 1x, sonstige Felder 0.5x.
    Der Tool-Call selbst zählt NICHT neu (total_calls unverändert — es war
    kein neuer Call, nur ein Ergebnis). Observer: wirft nie.
    """
    target = tool_name
    if tool_name in ("skill_view", "view_skill", "skills_view"):
        target = (args or {}).get("name") or tool_name
    try:
        fields = _result_text_fields(result)
        # User-Wörter (Entscheidungsphase) als Primärsignal IMMER lernen —
        # auch wenn das Ergebnis keine Lern-Felder hat (Option A: Plaintext
        # ist Rauschen, aber die User-Message bleibt das Kern-Signal).
        user_words = learn_words(user_message, lexicon, df_generic)
        if user_words:
            _lexicon_add(lexicon, stats, target, user_words, 1)
        if not fields:
            return lexicon, stats
        # Ergebnis-Wörter je Feld mit Feld-Gewicht (body 1x=2, sonst 0.5x=1)
        for field, text in fields:
            weight = (
                RESULT_BOOST_WEIGHT if field in RESULT_BOOST_FIELDS
                else RESULT_WORD_WEIGHT
            )
            result_words = learn_words(text, lexicon, df_generic)
            if not result_words:
                continue
            _lexicon_add(
                lexicon, stats, target,
                result_words[:MAX_RESULT_WORDS], weight,
            )
    except Exception:  # noqa: S110, BLE001 — Observer: niemals den Agent-Loop brechen
        pass
    return lexicon, stats


# ── LLM-Antworten (post_llm_call) — Task 2 ──────────────────────────────────
# assistant_response ist eine weitere FOLGE-Lern-Eingabe. Löst das
# 'ja, Option A'-Problem: Die Nutzer-Bestätigung ist nur mit dem LLM-Output
# zusammen verständlich — die Fachbegriffe stehen in der Antwort. Bei
# Bestätigungs-Mustern wird zusätzlich die letzte Assistant-Antwort aus der
# History beigemischt (dort stehen die Optionen).
RESPONSE_CONFIRM_PATTERN = re.compile(
    r"\b(option|entscheid|nehmen wir|wir nehmen|passt|lieber|besser)\b",
    re.IGNORECASE,
)
RESPONSE_MAX_CHARS = 500
RESPONSE_HISTORY_CHARS = 300   # nur der relevante Teil der letzten Antwort
_OPTION_CHOICE_PATTERN = re.compile(
    r"option\s+([a-z0-9])", re.IGNORECASE
)


def _history_option_text(
    conversation_history: object, chosen_option: str | None
) -> str:
    """Text der GEWÄHLTEN Option aus der letzten Assistant-Antwort.

    Löst 'Option A' präzise auf: Statt die ganze History-Antwort beizumischen
    (die auch die nicht gewählten Optionen enthält → Rauschen), wird nur die
    Zeile der gewählten Option extrahiert. Ohne erkennbare Option: '' (kein
    Signal — nicht die ganze Antwort lernen).
    """
    if not chosen_option:
        return ""
    if not isinstance(conversation_history, (list, tuple)):
        return ""
    for entry in reversed(conversation_history):
        if isinstance(entry, str):
            text = entry
        elif isinstance(entry, dict) and entry.get("role") == "assistant":
            content = entry.get("content") or ""
            if isinstance(content, (list, tuple)):
                content = " ".join(str(v) for v in content)
            text = str(content)
        else:
            continue
        # Zeile der gewählten Option: 'Option A: ...' — stoppt am nächsten
        # 'Option'-Token oder Zeilenende (nicht die verworfenen Optionen mitnehmen)
        pattern = re.compile(
            rf"option\s+{re.escape(chosen_option)}\s*[:)\-–—]?"
            r"[^\n]*?(?=\s+option\s+[a-z0-9]|\n|$)",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            return m.group(0)[:RESPONSE_HISTORY_CHARS]
    return ""


def learn_from_response(
    user_message: str,
    assistant_response: str,
    conversation_history: object,
    lexicon: dict,
    stats: dict,
    df_generic: set[str] | None = None,
) -> tuple[dict, dict]:
    """LLM-Antwort (post_llm_call) als Lern-Eingabe verwenden.

    Die Antwort enthält die tatsächlich gewählten/verwendeten Fachbegriffe
    (z. B. 'wir nehmen Option A: Riverpod'). Löst das 'ja, Option A'-Problem:
    Die Nutzer-Bestätigung ist nur mit dem LLM-Output zusammen verständlich.

    Mechanismus (kausal sauber): Die Antwort-Fachwörter verstärken die Skills,
    die mit den User-Wörtern dieser Aufgabe bereits assoziiert sind. Ohne
    bestehende Assoziation wird nichts gelernt (kein Signal — SoK-Warnung:
    ungefiltertes Lernen aus Modell-Output degradiert). Bei Bestätigungs-
    Mustern wird NUR die Zeile der gewählten Option aus der History extrahiert
    (nicht die ganze Antwort — sonst lernt man auch die verworfenen Optionen).
    """
    try:
        response_text = str(assistant_response or "")[:RESPONSE_MAX_CHARS]
        response_words = learn_words(response_text, lexicon, df_generic)
        if not response_words:
            return lexicon, stats
        # Entscheidungs-Kontext: 'Option A' präzise über die History auflösen
        if RESPONSE_CONFIRM_PATTERN.search(response_text):
            choice_m = _OPTION_CHOICE_PATTERN.search(response_text)
            if choice_m:
                history_text = _history_option_text(
                    conversation_history, choice_m.group(1).casefold()
                )
                if history_text:
                    response_words += learn_words(history_text, lexicon, df_generic)
        # Skills finden, die die User-Wörter dieser Aufgabe bereits kennen
        user_words = learn_words(user_message, lexicon, df_generic)
        target_skills: set[str] = set()
        for w in user_words:
            entry = lexicon.get(w)
            if not entry:
                continue
            for skill_name, count in entry.items():
                if count >= MIN_COOCCUR:
                    target_skills.add(skill_name)
        if not target_skills:
            return lexicon, stats  # kein Signal — nichts lernen
        # Antwort-Fachwörter verstärken genau diese Skills
        for skill_name in target_skills:
            _lexicon_add(
                lexicon, stats, skill_name,
                response_words[:MAX_RESULT_WORDS], RESULT_WORD_WEIGHT,
            )
    except Exception:  # noqa: S110, BLE001 — Observer: niemals den Agent-Loop brechen
        pass
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


def word_status(
    word: str,
    lexicon: dict,
    stats: dict,
    best_tool: str | None = None,
    best_lift: float = 0.0,
    best_co: int = 0,
) -> str:
    """Anzeige-Status eines Wortes — EINE Quelle für Engine + Dashboard.

    - "beobachtet": zu wenige Daten (total_calls < MIN_CALLS_FOR_LIFT) oder
      1x-Zufall (co < MIN_COOCCUR)
    - "kausal": Lift >= LIFT_THRESHOLD UND Support, UND das Wort ist nicht
      generisch (weniger als GENERIC_SKILL_THRESHOLD Skill-Assoziationen —
      die Engine behandelt es sonst beim Lernen/Matching als generisch)
    - "generisch": Kookkurrenz ohne Kausalität (wird beim nächsten Prune
      entfernt) oder zu viele Skill-Assoziationen
    """
    total_calls = stats.get("total_calls", 0)
    if total_calls < MIN_CALLS_FOR_LIFT:
        return "beobachtet"
    if len(lexicon.get(word, {})) >= GENERIC_SKILL_THRESHOLD:
        return "generisch"  # Engine behandelt es beim Lernen als generisch
    if best_co >= MIN_COOCCUR and best_lift >= LIFT_THRESHOLD:
        return "kausal"
    if best_co >= MIN_COOCCUR:
        return "generisch"  # beim nächsten Prune entfernt
    return "beobachtet"


def prune_lexicon(lexicon: dict, stats: dict) -> dict:
    """Nutzungsbasierte Bereinigung: Woerter ohne kausale Assoziation zu IRGENDEINEM
    Tool (bestes Lift < LIFT_THRESHOLD mit Minimum-Support) entfernen.
    Erst ab MIN_CALLS_FOR_LIFT — vorher ist der Lift zu verrauscht.
    Frische Woerter (Gesamt-Kookkurrenz < MIN_COOCCUR) werden verschont,
    damit neue Assoziationen nach dem Lift-Start noch anwachsen koennen."""
    if stats.get("total_calls", 0) < MIN_CALLS_FOR_LIFT:
        return lexicon
    keep = {}
    for w, tools in lexicon.items():
        if sum(tools.values()) < MIN_COOCCUR:
            keep[w] = tools  # zu wenig Daten — kann noch wachsen
            continue
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
    topics: list[dict] = []
    lines = text.splitlines()
    current: dict | None = None
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
    words: set[str] = set()
    for w in re.findall(r"[a-zäöüß]{4,}", desc.lower()):
        if w not in STOPWORDS and len(words) < limit:
            words.add(w)
    return words


def scan_skills(skills_dir: Path) -> list[dict]:
    """Alle installierten Skills: Kategorie, Name, Tags, Description-Wörter.

    Rekursiv (rglob) — findet auch Nicht-Standard-Strukturen (Pitfall 31):
    Kategorie-Direktdatei (cat/SKILL.md) und 3-stufig (cat/subcat/skill/SKILL.md).
    Kategorie = Top-Level-Ordner unter skills_dir (Semantik unverändert).
    """
    skills = []
    for md in sorted(skills_dir.rglob("SKILL.md")):
        rel = md.relative_to(skills_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            txt = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^name:\s*[\"']?([^\"'\n]+)", txt, re.MULTILINE)
        name = m.group(1).strip() if m else md.parent.name
        tags = []
        m2 = re.search(r"hermes:\s*\n\s*tags:\s*\[([^\]]*)\]", txt)
        if m2:
            tags = [t.strip().strip("'\"") for t in m2.group(1).split(",")]
        else:
            m3 = re.search(r"^tags:\s*\[([^\]]*)\]", txt, re.MULTILINE)
            if m3:
                tags = [t.strip().strip("'\"") for t in m3.group(1).split(",")]
        m4 = re.search(r"^description:\s*[\"']?([^\"'\n]+)", txt, re.MULTILINE)
        desc = m4.group(1).strip() if m4 else ""
        skills.append({
            "cat": rel.parts[0],
            "name": name,
            "tags": tags[:3],
            "desc_words": _desc_words(desc),
        })
    return skills


# ── Dynamische DF-Generik (Schritt 7) ───────────────────────────────────────
# Statische STOPWORDS sind sprachspezifisch und manuell zu pflegen. Wörter,
# die VIELE Skills beschreiben (hohe Dokumentfrequenz), sind keine Signale —
# das gilt sprachunabhängig und selbstpflegend. Diese dynamische Generik
# ergänzt die statische Liste beim Matching UND beim Lernen.
GENERIC_DF_RATIO = 0.4  # Wort in >= 40% aller Skills = generisch (kein Signal)

# Cache: Skill-Scan ist teuer, Skills ändern sich selten — einmal pro
# SKILL.md-mtime-Bestand berechnen.
_df_cache: dict = {"mtime": None, "words": frozenset()}


def cached_generic_words(skills_dir: Path) -> set[str]:
    """DF-Generik mit mtime-Cache (für Lern-Hooks; Matching nutzt den Scan)."""
    try:
        mtime = max(p.stat().st_mtime for p in skills_dir.rglob("SKILL.md"))
    except OSError:
        return set()
    if _df_cache["mtime"] != mtime:
        _df_cache["words"] = frozenset(generic_words(scan_skills(skills_dir)))
        _df_cache["mtime"] = mtime
    return set(_df_cache["words"])


def generic_words(skills: list[dict]) -> set[str]:
    """Wörter mit hoher Dokumentfrequenz über alle Skills.

    Zählt jedes Wort aus Tags + Name + Kategorie + Description-Wörtern über
    die Skill-Menge. Wörter, die >= GENERIC_DF_RATIO der Skills beschreiben,
    unterscheiden nichts mehr -> generisch. Sprachunabhängig: Die DF ist
    rein statistisch (ein deutsches Füllwort hat dieselbe DF wie ein englisches).
    """
    total = max(len(skills), 1)
    counts: dict[str, int] = {}
    for s in skills:
        seen: set[str] = set()
        for tag in s["tags"]:
            seen |= _norm_words(tag)
        seen |= _norm_words(s["name"])
        seen |= _norm_words(s["cat"])
        seen |= s["desc_words"]
        for w in seen:
            counts[w] = counts.get(w, 0) + 1
    return {w for w, c in counts.items() if c / total >= GENERIC_DF_RATIO}


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
    for m in _WORD_PATTERN.finditer(user_message.lower()):
        w = m.group(0)
        if w not in STOPWORDS and re.search(r"[a-zäöüß]", w):
            words.add(w)
    return words


# ── Learning hardening (privacy) ─────────────────────────────────────────────

_ID_PATTERN = re.compile(r"^(?=.*\d)[a-z0-9]{8,}$")  # hashes/IDs (8+ alnum WITH digit); pure-letter words are vocabulary
_TASK_ID_PATTERN = re.compile(r"^t_[a-z0-9]+$")       # task IDs (t_<id>)
MAX_LEARN_WORDS = 5                                   # max keywords per learning event
MAX_LEARN_MESSAGE_WORDS = 40                          # longer messages = context, not learned


def learn_words(
    user_message: str,
    lexicon: dict | None = None,
    df_generic: set[str] | None = None,
) -> list[str]:
    """Task keywords for learning — in message order, hardened.

    - Only from SHORT messages (<= 40 words): long messages carry context
      or explanations, not concise task keywords.
    - IDs, hashes, task IDs (t_...) are never learned.
    - Words already associated with >= GENERIC_SKILL_THRESHOLD skills are
      skipped (generic vocabulary, e.g. from mass skill-load sessions).
    - Words with high document frequency across skills (df_generic, Schritt 7)
      are skipped — they describe many skills and are no signal.
    - At most 5 keywords per event (the first relevant ones).
    """
    if len(user_message.split()) > MAX_LEARN_MESSAGE_WORDS:
        return []
    result: list[str] = []
    for m in _WORD_PATTERN.finditer(user_message.lower()):
        w = m.group(0)
        if w in STOPWORDS or not re.search(r"[a-zäöüß]", w):
            continue
        if _ID_PATTERN.match(w) or _TASK_ID_PATTERN.match(w):
            continue
        if df_generic and w in df_generic:
            continue  # DF-generisch — beschreibt viele Skills, kein Signal
        if lexicon:
            entry = lexicon.get(w)
            if entry and len(entry) >= GENERIC_SKILL_THRESHOLD:
                continue  # generisch — kein weiteres Lernen
        result.append(w)
        if len(result) >= MAX_LEARN_WORDS:
            break
    return result


def context_words(
    extra_context: dict, df_generic: set[str] | None = None
) -> set[str]:
    """Match-Wörter aus dem Session-Puffer (Task 3).

    Extrahiert relevante Wörter aus ``tool_results`` (Liste von Tool-
    Ergebnis-Strings/-Objekten) und ``last_response`` (letzte LLM-Antwort).
    Nutzt die Ergebnis-Feld-Logik (nur body/output/text/description/result/
    summary, Größen-Deckel, Fehler-Status ignoriert) und die learn_words-
    Härtung (IDs/Hashes/Generik nie als Match-Wörter).
    """
    words: set[str] = set()
    for result in extra_context.get("tool_results") or []:
        for _field, text in _result_text_fields(result):
            words |= set(learn_words(text, df_generic=df_generic))
    last_response = extra_context.get("last_response") or ""
    if last_response:
        words |= set(
            learn_words(str(last_response)[:RESPONSE_MAX_CHARS], df_generic=df_generic)
        )
    return words


def build_injection(
    user_message: str,
    skills_dir: Path,
    matrix_path: Path | None = None,
    lexicon: dict | None = None,
    stats: dict | None = None,
    extra_context: dict | None = None,
) -> str | None:
    """Injektion bauen: erkannte Matrix-Themen + passende Skills.

    extra_context (Session-Puffer, Task 3): Wörter aus vorherigen
    Tool-Ergebnissen (``tool_results``) und der letzten LLM-Antwort
    (``last_response``) erweitern die Match-Fläche — eine Folge-Aufgabe
    („mach weiter") matcht gegen den Kanban-Body des vorherigen Turns.

    Returns None, wenn weder Thema noch Skill matcht (Aufrufer entscheidet,
    ob der kurze Fallback-Hinweis injiziert wird).
    """
    topics: list[dict] = []
    if matrix_path is not None and matrix_path.exists():
        topics = parse_matrix(matrix_path.read_text(encoding="utf-8"))
    skills = scan_skills(skills_dir)
    lexicon = lexicon or {}
    # Dynamische DF-Generik (Schritt 7): Wörter, die viele Skills beschreiben,
    # sind keine Signale — sprachunabhängig, selbstpflegend.
    df_generic = generic_words(skills)

    # Themen matchen
    topic_hits = []
    for t in topics:
        score = _phrase_hits(user_message, t["keywords"])
        if score > 0:
            topic_hits.append((score, t))
    topic_hits.sort(key=lambda x: -x[0])

    # Skills matchen (Tags + Name + Kategorie + Description-Wörter + Lexikon)
    words = _task_words(user_message)
    if extra_context:
        words |= context_words(extra_context)
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
        score = len((words - STOPWORDS - df_generic) & hay)
        # Gelernte Assoziationen: count als Gewicht
        for w in words & set(lexicon):
            if len(lexicon[w]) >= GENERIC_SKILL_THRESHOLD or w in df_generic:
                continue  # generisches Wort — kein Gewicht
            count = lexicon[w].get(s["name"], 0)
            if count == 0:
                continue
            if (
                stats
                and stats.get("total_calls", 0) >= MIN_CALLS_FOR_LIFT
                and (count < MIN_COOCCUR or lift(w, s["name"], lexicon, stats) < LIFT_THRESHOLD)
            ):
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
    topics = tuple(sorted(re.findall(r"^- ([A-Za-zäöüÄÖÜ0-9 /-]+?) \(Match", injection, re.MULTILINE)))
    skills = tuple(sorted(re.findall(r"-\s+(?:Pflicht|Required|Optional): ([^\n]+)", injection)))
    return topics + skills


# ── Lernen aus Tool-Nutzung ──────────────────────────────────────────────────
# `record_tool_call` (oben) ersetzt das fruehere Skill-Load-Lernen: Jeder
# Tool-Start (inkl. skill_view) erfasst die Woerter der Entscheidungsphase
# als Kookkurrenz — der Lift filtert generische Woerter (Kausalitaet).
