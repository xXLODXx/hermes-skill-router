"""Stable, compact rendering for v2 decisions."""

from __future__ import annotations

from .models import RoutingDecision

FALLBACK = "No high-confidence skill match. Continue with the normal skill index."


def render(decision: RoutingDecision) -> str | None:
    if not decision.candidates:
        return None
    lines = ["## Skill Router v2 — begründete Ergänzungen"]
    for candidate in decision.candidates:
        evidence = ", ".join(sorted({item.kind for item in candidate.evidence}))
        lines.append(f"- {candidate.skill.category}/{candidate.skill.name} ({candidate.decision}; confidence {candidate.confidence:.2f}; evidence: {evidence})")
    return "\n".join(lines)
