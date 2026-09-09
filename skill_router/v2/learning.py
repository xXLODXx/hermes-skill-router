"""Separated, opt-in learning event policy for v2."""

from __future__ import annotations

import os


def output_learning_enabled() -> bool:
    """Explicit opt-in until v2 replay tests establish net benefit."""
    value = os.environ.get("SKILL_ROUTER_V2_OUTPUT_LEARNING")
    return bool(value and value.strip().casefold() in {"1", "true", "yes", "on"})
