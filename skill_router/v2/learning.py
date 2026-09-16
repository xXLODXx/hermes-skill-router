"""Separated event policies for v2 (learning, context rescue).

Both policies are environment-gated with explicit semantics; neither writes
anything to disk — session context stays in RAM and expires with the store TTL.
"""

from __future__ import annotations

import os


def output_learning_enabled() -> bool:
    """Explicit opt-in until v2 replay tests establish net benefit."""
    value = os.environ.get("SKILL_ROUTER_V2_OUTPUT_LEARNING")
    return bool(value and value.strip().casefold() in {"1", "true", "yes", "on"})


def context_rescue_enabled() -> bool:
    """Context rescue: re-check empty follow-up turns against recent context.

    Default ON — bounded (last tool results + last reply, hard caps) and
    RAM-only. Explicit disable via ``SKILL_ROUTER_CONTEXT_RESCUE=0/false/no/off``.
    """
    value = os.environ.get("SKILL_ROUTER_CONTEXT_RESCUE")
    if value is None:
        return True
    return value.strip().casefold() in {"1", "true", "yes", "on"}
