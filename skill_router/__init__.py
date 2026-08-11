"""Hermes Skill Router — task-aware, self-learning skill discovery.

Registers two hooks:

- ``pre_llm_call``: on the first turn of a session (and on topic changes)
  injects a compact list of matching routing-matrix topics and skills,
  matched against the user's task via keyword scoring. No match -> a single
  short fallback hint per session. Token cost: ~70-200 tokens per injection.
- ``on_skill_lifecycle``: when the model loads a skill that was NOT part of
  the injection, the task's keywords are persistently associated with that
  skill (learned_keywords.json). The matching grows with real usage patterns.

Requires nothing beyond a stock Hermes install. All paths resolve against
``HERMES_HOME``; the routing matrix is optional (see README).
"""

import os
import re
from pathlib import Path

from . import engine

_PLUGIN_DIR = Path(__file__).resolve().parent
_LEXICON_PATH = _PLUGIN_DIR / "data" / "learned_keywords.json"
_MAX_LEARN_EVENTS_PER_SESSION = 1  # nur erstes Lern-Event pro Session (Massen-Events vermeiden)

_session_ctx: dict = {"current": None, "last_match": (), "fallback_shown": False}
_learn_counts: dict[str, int] = {}  # session_id -> Lern-Events (Massen-Events-Bremse)


def register(ctx):
    """Plugin entry point: wires the injection and learning hooks."""

    def inject(user_message: str, session_id: str, **kwargs):
        matrix = engine.default_matrix_path()
        try:
            injection = engine.build_injection(
                user_message or "",
                engine.hermes_home() / "skills",
                matrix,
                engine.load_lexicon(_LEXICON_PATH),
            )
        except OSError:
            injection = None

        if not injection:
            # No match: fallback hint at most once per session.
            if _session_ctx.get("last_match") or _session_ctx.get("fallback_shown"):
                _session_ctx["current"] = None
                return None
            _session_ctx["fallback_shown"] = True
            _session_ctx["current"] = {
                "message": user_message or "",
                "injected": set(),
            }
            return {"context": engine.FALLBACK_HINT}

        signature = engine.match_signature(injection)
        if signature and signature == _session_ctx.get("last_match"):
            return None  # same topic — no repeated injection
        if not signature and _session_ctx.get("last_match"):
            return None  # follow-up without match — no repeated fallback
        _session_ctx["last_match"] = signature
        _session_ctx["fallback_shown"] = False
        _session_ctx["current"] = {
            "message": user_message or "",
            "injected": set(re.findall(r"/([a-z0-9-]+)", injection)),
        }
        return {"context": injection}

    def learn(skill_name: str, action: str, session_id: str, **kwargs):
        if action != "loaded":
            return
        if _learn_counts.get(session_id, 0) >= _MAX_LEARN_EVENTS_PER_SESSION:
            return  # nur das erste Lern-Event pro Session
        ctx_ = _session_ctx.get("current")
        if not ctx_:
            return
        lexicon = engine.load_lexicon(_LEXICON_PATH)
        updated = engine.learn_from_load(
            ctx_["message"], ctx_["injected"], skill_name, lexicon
        )
        if updated != lexicon:
            engine.save_lexicon(updated, _LEXICON_PATH)
            _learn_counts[session_id] = _learn_counts.get(session_id, 0) + 1

    ctx.register_hook("pre_llm_call", inject)
    ctx.register_hook("on_skill_lifecycle", learn)
