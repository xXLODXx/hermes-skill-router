#!/usr/bin/env python3
"""Pre-commit guard: verhindert, dass persönliche Daten ins Repo gelangen.

Blockt Commits, deren staged Dateien persönliche Muster enthalten
(IP-Adressen, Benutzerpfade, Task-IDs, Namen) oder die Lern-Datei
learned_keywords.json einschleusen wollen. Läuft als pre-commit-Hook
(.githooks/pre-commit ruft dieses Skript auf).

Keine externen Abhängigkeiten — reine Standardbibliothek.
"""

import re
import subprocess
import sys
from pathlib import Path

# Generische Muster — unkritisch, können im Repo stehen
PATTERNS = [
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP-Adresse"),
    (r"[Cc]:\\[Uu]sers\\", "Windows-Benutzerpfad"),
    (r"\bt_[a-z0-9]{8}\b", "Task-ID"),
    (r"\bapi\.[a-z0-9-]+\.de\b", "private Domain"),
]

# Persönliche Muster aus lokaler Datei (nie im Repo!)
_PERSONAL_PATTERNS_FILE = Path.home() / ".hermes" / "guard-personal-patterns.txt"


def _load_personal_patterns() -> list[tuple[str, str]]:
    """Persönliche Muster laden: eine Regex pro Zeile, label = 'persönlich'."""
    try:
        lines = _PERSONAL_PATTERNS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    patterns = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append((line, "persönliches Muster"))
    return patterns


# Dateien, die niemals committet werden dürfen (Lern-Daten mit Nutzer-Wörtern)
FORBIDDEN_FILES = {
    "learned_keywords.json",
    "learned_keywords.train.json",
    "tool_stats.json",
    "tool_stats.train.json",
}


def main() -> int:
    files = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()

    all_patterns = PATTERNS + _load_personal_patterns()

    problems: list[str] = []
    for f in files:
        if not f:
            continue
        if f.split("/")[-1] in FORBIDDEN_FILES:
            problems.append(f"{f}: Lern-Datei darf nie committet werden")
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        for pattern, label in all_patterns:
            for m in re.finditer(pattern, content):
                problems.append(f"{f}: {label} gefunden: {m.group(0)!r}")

    if problems:
        print("PRE-COMMIT BLOCKIERT — potenzielle persönliche Daten in staged Dateien:")
        for p in problems[:20]:
            print(f"  - {p}")
        print("\nEntferne die betroffenen Daten oder committe sie nicht.")
        return 1
    print("Guard OK: keine persönlichen Daten in den staged Dateien.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
