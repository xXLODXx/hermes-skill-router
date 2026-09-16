"""Hermes Skill Router v2 plugin wrapper.

The v2 runtime is deliberately separate from the legacy compatibility engine:
all routing decisions go through the session-safe, evidence-based pipeline in
``skill_router.v2``. The legacy ``engine`` module remains importable while
existing dashboard/compatibility tests migrate.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import engine
from .v2.audit import record as record_audit
from .v2.catalog import scan_catalog
from .v2.evidence import tokens
from .v2.learning import context_rescue_enabled, output_learning_enabled
from .v2.models import Evidence, SessionTurn
from .v2.render import FALLBACK, render
from .v2.selector import select
from .v2.session import SessionStore

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_AUDIT_PATH = _PLUGIN_DIR / "data" / "v2_injections.jsonl"
_STORE = SessionStore()

# Matrix parse cache: parsed topics per (path, mtime_ns, size). The matrix is
# re-read only when the file actually changed — the hook runs every turn.
_MATRIX_CACHE: dict[tuple[str, int, int], list[dict]] = {}
_MAX_MATRIX_CACHE = 8

# Context-rescue bounds: last tool results / assistant reply of the SAME
# session, in-memory only, never persisted or transmitted.
_RESCUE_RESULTS = 2
_RESCUE_RESULT_CHARS = 500
_RESCUE_REPLY_CHARS = 800
_RESULT_FIELDS = ("body", "output", "text", "description", "result", "summary")


def _loaded_names(kwargs: dict) -> set[str]:
    values = kwargs.get("loaded_skills") or kwargs.get("active_skills") or ()
    if isinstance(values, str):
        return {values}
    return {str(value) for value in values if value}


def _profile_name(home: Path) -> str:
    """Diagnostic profile label derived from the home path (never raw paths)."""
    try:
        home = home.expanduser().resolve()
    except OSError:
        home = home.expanduser()
    if home.parent.name == "profiles":
        return home.name
    return "default"


def _matrix_path() -> Path | None:
    """Resolve the active workflow matrix without requiring a config edit."""
    configured = os.environ.get("SKILL_ROUTER_MATRIX_PATH")
    if configured:
        return Path(configured)
    candidate = engine.hermes_home() / "skills" / "software-development" / "workflow-router" / "references" / "workflow-matrix.md"
    return candidate if candidate.exists() else None


def _matrix_topics(path: Path) -> list[dict]:
    """Parse the matrix once per file revision (mtime-keyed cache)."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _MATRIX_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        topics = engine.parse_matrix(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return []
    if len(_MATRIX_CACHE) >= _MAX_MATRIX_CACHE:
        _MATRIX_CACHE.clear()
    _MATRIX_CACHE[key] = topics
    return topics


def _matrix_evidence(message: str) -> tuple[dict[str, tuple[Evidence, ...]], str]:
    """(skill -> matrix evidence, matrix file name) for the matched topics."""
    path = _matrix_path()
    if path is None:
        return {}, ""
    message_folded = message.casefold()
    message_tokens = tokens(message)
    result: dict[str, list[Evidence]] = {}
    for topic in _matrix_topics(path):
        keywords = [str(keyword).casefold() for keyword in topic.get("keywords", [])]
        matched = any(keyword in message_folded or set(tokens(keyword)) & message_tokens for keyword in keywords)
        if not matched:
            continue
        topic_name = str(topic.get("name", "unbenannt"))
        for role, field in (("Pflicht", "pflicht"), ("Optional", "optional")):
            for name in topic.get(field, []):
                canonical = str(name).casefold()
                result.setdefault(canonical, []).append(
                    Evidence("matrix", topic_name, 6.0 if role == "Pflicht" else 4.0, f"Matrix: {role}")
                )
    return {name: tuple(items) for name, items in result.items()}, path.name


def _result_text(result: object) -> str:
    """Bounded textual view of one tool result (whitelisted string fields only)."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for field in _RESULT_FIELDS:
            value = result.get(field)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _context_snippets(turn: SessionTurn) -> str:
    """Recent tool results + last assistant reply, bounded and RAM-only."""
    parts: list[str] = []
    for result in turn.tool_results[-_RESCUE_RESULTS:]:
        text = _result_text(result).strip()
        if text:
            parts.append(text[:_RESCUE_RESULT_CHARS])
    reply = (turn.last_response or "").strip()
    if reply:
        parts.append(reply[:_RESCUE_REPLY_CHARS])
    return "\n".join(parts)


def _buffering_enabled() -> bool:
    """Keep the bounded session context (rescue needs it; learning consumed it)."""
    return context_rescue_enabled() or output_learning_enabled()


def register(ctx):
    """Register v2 hooks with fail-closed session handling."""

    def inject(user_message: str, session_id: str, **kwargs):
        if not session_id:
            return None
        turn = _STORE.begin(session_id, user_message or "")
        if turn is None:
            return None
        home = engine.hermes_home()
        skills = scan_catalog(home / "skills")
        loaded = _loaded_names(kwargs) | turn.already_loaded
        matrix, matrix_source = _matrix_evidence(user_message or "")
        decision = select(user_message or "", skills, already_loaded=loaded, matrix=matrix)
        rescued = False
        if not decision.candidates and context_rescue_enabled():
            snippets = _context_snippets(turn)
            if snippets:
                combined = f"{user_message or ''}\n{snippets}".strip()
                rescue_matrix, _ = _matrix_evidence(combined)
                rescue_decision = select(combined, skills, already_loaded=loaded, matrix=rescue_matrix)
                if rescue_decision.candidates:
                    decision = rescue_decision
                    rescued = True
        names = tuple(item.skill.canonical_name for item in decision.candidates)
        context = render(decision)
        rendered_chars = len(context) if context else 0

        def _record(emitted: bool = False) -> None:
            record_audit(
                _AUDIT_PATH,
                session_id,
                decision,
                catalog_size=len(skills),
                profile=_profile_name(home),
                matrix_source=matrix_source,
                rescue=rescued,
                rendered_chars=rendered_chars,
                fallback_emitted=emitted,
            )

        if not names:
            emitted = bool(kwargs.get("is_first_turn")) and not turn.fallback_emitted
            _STORE.update(session_id, already_loaded=loaded, fallback_emitted=turn.fallback_emitted or emitted)
            _record(emitted=emitted)
            return {"context": FALLBACK} if emitted else None
        if names == turn.last_signature:
            _STORE.update(session_id, already_loaded=loaded)
            _record()
            return None
        _STORE.update(
            session_id,
            last_signature=names,
            injected=set(names),
            already_loaded=loaded,
        )
        _record()
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

    def on_tool_result(function_name: str = "", result: object = None, session_id: str = "", **kwargs):
        if not session_id or not _buffering_enabled():
            return
        turn = _STORE.get(session_id)
        if turn is not None:
            results = [*turn.tool_results, result][-3:]
            _STORE.update(session_id, tool_results=results)
        return

    def on_llm_response(
        assistant_response: str = "", conversation_history: object = None, session_id: str = "", **kwargs
    ):
        if not session_id or not _buffering_enabled():
            return
        if _STORE.get(session_id) is not None:
            _STORE.update(session_id, last_response=str(assistant_response or "")[:2000])
        return

    ctx.register_hook("pre_llm_call", inject)
    ctx.register_hook("pre_tool_call", on_tool)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_hook("post_llm_call", on_llm_response)
