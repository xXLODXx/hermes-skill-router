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

# (Regex, Beschreibung) — Muster, die NIE im Repo landen dürfen
PATTERNS = [
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "IP-Adresse"),
    (r"[Cc]:\\[Uu]sers\\", "Windows-Benutzerpfad"),
    (r"\bt_[a-z0-9]{8}\b", "Task-ID"),
    (r"\b[PERSON1]\b", "Benutzername"),
    (r"\b[PERSON2]\b", "Benutzername"),
    (r"[Ss]enioren[- ]?[Ll]otse", "Projektname"),
    (r"\bapi\.[a-z0-9-]+\.de\b", "private Domain"),
]

# Dateien, die niemals committet werden dürfen (Lern-Daten mit Nutzer-Wörtern)
FORBIDDEN_FILES = {"learned_keywords.json"}


def main() -> int:
    files = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()

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
        for pattern, label in PATTERNS:
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
