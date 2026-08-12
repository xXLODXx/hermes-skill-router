"""Skill-Router Plugin — Root-Einstieg für das Hermes-Plugin-System.

Das Plugin-System lädt ``<plugin-dir>/__init__.py`` mit einer
``register(ctx)``-Funktion. Die eigentliche Implementierung liegt im
``skill_router``-Paket; dieser Wrapper re-exportiert nur den Einstieg.

Der Loader lädt diesen Wrapper als isoliertes Modul — das Plugin-Verzeichnis
ist dabei NICHT im ``sys.path``. Ohne den Eintrag schlägt
``from skill_router import register`` fehl („No module named 'skill_router'")
und das Plugin wird gar nicht aktiv (keine Hooks). Das Plugin-Verzeichnis
macht sich daher selbst bekannt.
"""

import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from skill_router import register  # noqa: E402

__all__ = ["register"]
