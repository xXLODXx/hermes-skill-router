"""Hermes Skill Router v2 plugin wrapper.

The v2 runtime is deliberately separate from the legacy compatibility engine:
all routing decisions go through the session-safe, evidence-based pipeline in
``skill_router.v2``. The legacy ``engine`` module remains importable while
existing dashboard/compatibility tests migrate.
"""

from __future__ import annotations

from pathlib import Path

from . import engine
from .v2.audit import record as record_audit
from .v2.catalog import scan_catalog
from .v2.learning import output_learning_enabled
from .v2.render import render
from .v2.selector import select
from .v2.session import SessionStore

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_AUDIT_PATH = _PLUGIN_DIR / "data" / "v2_injections.jsonl"
_STORE = SessionStore()


def _loaded_names(kwargs: dict) -> set[str]:
    values = kwargs.get("loaded_skills") or kwargs.get("active_skills") or ()
    if isinstance(values, str):
        return {values}
    return {str(value) for value in values if value}


def register(ctx):
    """Register v2 hooks with fail-closed session handling."""

    def inject(user_message: str, session_id: str, **kwargs):
        if not session_id:
            return None
        turn = _STORE.begin(session_id, user_message or "")
        if turn is None:
            return None
        skills = scan_catalog(engine.hermes_home() / "skills")
        loaded = _loaded_names(kwargs) | turn.already_loaded
        decision = select(
            user_message or "",
            skills,
            already_loaded=loaded,
        )
        names = tuple(item.skill.canonical_name for item in decision.candidates)
        if names == turn.last_signature:
            _STORE.update(session_id, already_loaded=loaded)
            record_audit(_AUDIT_PATH, session_id, decision)
            return None
        _STORE.update(
            session_id,
            last_signature=names,
            injected=set(names),
            already_loaded=loaded,
        )
        record_audit(_AUDIT_PATH, session_id, decision)
        context = render(decision)
        return {"context": context} if context else None

    def on_tool(tool_name: str, session_id: str, **kwargs):
        if not session_id:
            return
        turn = _STORE.get(session_id)
        if turn is None:
            return
        args = kwargs.get("function_args") or kwargs.get("args") or {}
        target = args.get("name") if isinstance(args, dict) else None
        if tool_name == "skill_view" and target:
            loaded = set(turn.already_loaded)
            loaded.add(str(target))
            _STORE.update(session_id, already_loaded=loaded)
        return

    def on_tool_result(function_name: str, result: object, session_id: str = "", **kwargs):
        if not session_id or not output_learning_enabled():
            return
        turn = _STORE.get(session_id)
        if turn is not None:
            results = [*turn.tool_results, result][-3:]
            _STORE.update(session_id, tool_results=results)
        return

    def on_llm_response(
        assistant_response: str, conversation_history: object, session_id: str = "", **kwargs
    ):
        if not session_id or not output_learning_enabled():
            return
        if _STORE.get(session_id) is not None:
            _STORE.update(session_id, last_response=str(assistant_response or "")[:2000])
        return

    ctx.register_hook("pre_llm_call", inject)
    ctx.register_hook("pre_tool_call", on_tool)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_hook("post_llm_call", on_llm_response)
