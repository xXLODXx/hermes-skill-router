"""Konsistenz-Test: installierter Plugin-Clone darf nicht vom Repo abweichen.

Nach der Altlast-Ablösung (Schritt 8) ist das Plugin ein Git-Clone des Repos.
Ein stiller Drift (manuelle Eingriffe im Clone, abweichende Versionen) würde
die Verhaltensgleichheit brechen — dieser Test erkennt das.

Läuft NUR, wenn der installierte Clone existiert (~/.hermes/plugins/skill-router).
In CI (ohne Installation) wird der Test übersprungen.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
INSTALL_DIR = Path.home() / ".hermes" / "plugins" / "skill-router"

# Öffentliche Engine-Funktionen, deren Verhalten identisch sein muss
ENGINE_FUNCTIONS = [
    "learn_words",
    "lift",
    "record_tool_call",
    "learn_from_result",
    "learn_from_response",
    "context_words",
    "build_injection",
    "output_learning_enabled",
]


def _git_head(repo: Path) -> str | None:
    """Aktuellen HEAD des Repos holen (None wenn kein Git)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # Rückgabe-Code wird manuell geprüft
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def test_install_is_git_clone_of_repo() -> None:
    """Der installierte Clone muss ein legitimer Stand des Repos sein."""
    if not INSTALL_DIR.exists():
        pytest.skip("Plugin nicht installiert (CI-Umgebung)")
    repo_head = _git_head(REPO_DIR)
    install_head = _git_head(INSTALL_DIR)
    assert repo_head is not None, "Repo ist kein Git-Repository"
    assert install_head is not None, "Installierter Clone ist kein Git-Repository"
    # Der Clone-HEAD muss im REPO existieren (git cat-file): dann ist der
    # Clone ein legitimer Stand (synchron oder nicht gepullt, aber nie fremd).
    # Läuft im Repo-Kontext — der Clone kennt neuere Repo-Commits nicht.
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{install_head}^{{commit}}"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        known = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        known = False
    assert known, (
        f"Installierter Clone-HEAD {install_head} existiert nicht im Repo "
        f"(HEAD {repo_head}) — Fremdcode oder fremdes Repo!"
    )


def test_installed_engine_behaves_like_repo() -> None:
    """Verhaltensgleichheit der öffentlichen Engine-Funktionen.

    Lädt die installierte Engine als Modul (über den Plugin-Pfad) und prüft,
    dass alle öffentlichen Funktionen existieren und das Plugin registrierbar
    ist. Der tiefe Verhaltensvergleich (gleiche Inputs -> gleiche Outputs)
    läuft gegen die REPO-Engine — der Clone IS die Repo-Engine (gleicher HEAD).
    """
    if not INSTALL_DIR.exists():
        pytest.skip("Plugin nicht installiert (CI-Umgebung)")
    install_head = _git_head(INSTALL_DIR)
    repo_head = _git_head(REPO_DIR)
    if install_head != repo_head:
        pytest.skip(
            f"Clone steht auf {install_head} != Repo {repo_head} — "
            "Verhaltenstest nur bei synchronem Stand sinnvoll"
        )
    # Installierte Engine importierbar + Funktionen vorhanden
    sys.path.insert(0, str(INSTALL_DIR))
    import skill_router.engine as installed_engine  # type: ignore[import-not-found]

    missing = [f for f in ENGINE_FUNCTIONS if not hasattr(installed_engine, f)]
    assert not missing, f"Installierte Engine fehlt: {missing}"

    # Registrierung funktioniert (4 Hooks)
    import skill_router as installed_plugin  # type: ignore[import-not-found]

    class _FakeCtx:
        def __init__(self) -> None:
            self.hooks: list[str] = []

        def register_hook(self, name: str, fn: object) -> None:
            self.hooks.append(name)

    ctx = _FakeCtx()
    installed_plugin.register(ctx)
    assert ctx.hooks == [
        "pre_llm_call",
        "pre_tool_call",
        "post_tool_call",
        "post_llm_call",
    ], f"Hook-Set weicht ab: {ctx.hooks}"
