"""Skill-Router Plugin — Root-Einstieg für das Hermes-Plugin-System.

Das Plugin-System lädt ``<plugin-dir>/__init__.py`` mit einer
``register(ctx)``-Funktion. Die eigentliche Implementierung liegt im
``skill_router``-Paket; dieser Wrapper re-exportiert nur den Einstieg.
"""

from skill_router import register

__all__ = ["register"]
