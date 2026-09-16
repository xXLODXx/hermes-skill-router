"""Stable, compact rendering for v2 decisions."""

from __future__ import annotations

from .models import RoutingDecision

FALLBACK = "No high-confidence skill match. Continue with the normal skill index."


def render(decision: RoutingDecision) -> str | None:
    """Render the injection block.

    Compact format (v0.800): ``- <path> — <decision>, <confidence> (<kinds>)``.
    Measured against 236 live injections of the previous label-heavy format:
    -19 chars/line plus a shorter header, ~25 % smaller overall.
    """
    if not decision.candidates:
        return None
    lines = ["## Skill Router v2"]
    for candidate in decision.candidates:
        evidence = ", ".join(sorted({item.kind for item in candidate.evidence}))
        path = f"{candidate.skill.category}/{candidate.skill.name}" if candidate.skill.category else candidate.skill.name
        lines.append(f"- {path} — {candidate.decision}, {candidate.confidence:.2f} ({evidence})")
    return "\n".join(lines)
