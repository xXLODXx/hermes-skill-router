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

import re
from pathlib import Path

from . import engine

_PLUGIN_DIR = Path(__file__).resolve().parent
_LEXICON_PATH = _PLUGIN_DIR / "data" / "learned_keywords.json"
_STATS_PATH = _PLUGIN_DIR / "data" / "tool_stats.json"

_session_ctx: dict = {"current": None, "last_match": (), "fallback_shown": False}


def register(ctx):
    """Plugin entry point: wires the injection and learning hooks."""

    def _df_generic() -> set[str] | None:
        """Dynamische DF-Generik (Schritt 7) für die Lern-Hooks (mit Cache)."""
        try:
            return engine.cached_generic_words(engine.hermes_home() / "skills")
        except OSError:
            return None

    def inject(user_message: str, session_id: str, **kwargs):
        # Immer die aktuelle Message merken — die Entscheidungsphase, die das
        # Tool-Tracking (pre_tool_call) den Tool-Starts zuordnet.
        _session_ctx["current"] = {"message": user_message or "", "injected": set()}
        matrix = engine.default_matrix_path()
        try:
            injection = engine.build_injection(
                user_message or "",
                engine.hermes_home() / "skills",
                matrix,
                engine.load_lexicon(_LEXICON_PATH),
                engine.load_stats(_STATS_PATH),
                extra_context=(
                    {
                        "tool_results": _session_ctx.get("tool_results", [])[-3:],
                        "last_response": _session_ctx.get("last_response", ""),
                    }
                    if engine.output_learning_enabled()
                    else None
                ),
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
        _save_last_injection(
            user_message or "", injection, _PLUGIN_DIR / "data" / "last_injection.json"
        )
        return {"context": injection}

    def _save_last_injection(
        message: str, injection: str, path: Path
    ) -> None:
        """Letzte Injektion fürs Dashboard persistieren (Task -> Skills)."""
        try:
            import json as _json
            import re as _re
            import time as _time

            topics: list[str] = []
            skills: list[str] = []
            for line in injection.splitlines():
                line = line.strip()
                m_topic = _re.match(r"^- (.+?) \(Match \d+\)$", line)
                if m_topic:
                    topics.append(m_topic.group(1))
                    continue
                m_skill = _re.match(r"^- ([a-z0-9-]+/[a-z0-9-]+)", line)
                if m_skill:
                    skills.append(m_skill.group(1))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                _json.dumps(
                    {
                        "ts": _time.time(),
                        "message": message[:200],
                        "topics": topics[:5],
                        "skills": skills[:15],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: S110, BLE001 — Observer: nie den Agent-Loop brechen
            pass

    def on_tool(tool_name: str, session_id: str, **kwargs):
        """Jeden Tool-Start erfassen: Wörter der Entscheidungsphase (aktuelle
        User-Message) als Kookkurrenz — Grundlage für Lift-Gewichtung und
        nutzungsbasierte Bereinigung. Observer: blockt nie."""
        ctx_ = _session_ctx.get("current")
        if not ctx_ or not tool_name:
            return
        message = ctx_.get("message", "")
        if not message:
            return
        lexicon = engine.load_lexicon(_LEXICON_PATH)
        stats = engine.load_stats(_STATS_PATH)
        lexicon, stats = engine.record_tool_call(
            message, tool_name, kwargs.get("args"), lexicon, stats,
            df_generic=_df_generic(),
        )
        lexicon = engine.prune_lexicon(lexicon, stats)
        engine.save_lexicon(lexicon, _LEXICON_PATH)
        engine.save_stats(stats, _STATS_PATH)
        return

    def on_tool_result(function_name: str, result: object, **kwargs):
        """Tool-Ergebnis als Lern-Eingabe (post_tool_call, Output-Lernen).

        Löst die Indirektions-Lücke (Kanban-Task-Body): Wörter des
        Tool-Ergebnisses werden mit dem Skill assoziiert, der sie lieferte.
        Nur aktiv, wenn das Feature-Flag output_learning gesetzt ist
        (config.yaml, Default aus). Observer: blockt nie.
        """
        if not engine.output_learning_enabled():
            return
        ctx_ = _session_ctx.get("current")
        if not ctx_:
            return
        message = ctx_.get("message", "")
        if not function_name:
            return
        lexicon = engine.load_lexicon(_LEXICON_PATH)
        stats = engine.load_stats(_STATS_PATH)
        lexicon, stats = engine.learn_from_result(
            message,
            function_name,
            result,
            lexicon,
            stats,
            args=kwargs.get("function_args") or kwargs.get("args"),
            df_generic=_df_generic(),
        )
        engine.save_lexicon(lexicon, _LEXICON_PATH)
        engine.save_stats(stats, _STATS_PATH)
        # Session-Puffer (Task 3): Ergebnis für Folge-Injektionen merken
        if result is not None:
            _session_ctx.setdefault("tool_results", []).append(result)
            _session_ctx["tool_results"] = _session_ctx["tool_results"][-3:]
        return

    def on_llm_response(
        assistant_response: str, conversation_history: object, **kwargs
    ):
        """LLM-Antwort als Lern-Eingabe (post_llm_call, Output-Lernen).

        Löst das 'ja, Option A'-Problem: Die Fachbegriffe stehen in der
        assistant_response, nicht in der Nutzer-Bestätigung. Verstärkt die
        Skills, die die User-Wörter dieser Aufgabe bereits kennen.
        Nur aktiv bei Feature-Flag output_learning (Default aus). Observer.
        """
        if not engine.output_learning_enabled():
            return
        ctx_ = _session_ctx.get("current")
        if not ctx_:
            return
        message = ctx_.get("message", "")
        if not assistant_response:
            return
        lexicon = engine.load_lexicon(_LEXICON_PATH)
        stats = engine.load_stats(_STATS_PATH)
        lexicon, stats = engine.learn_from_response(
            message,
            assistant_response,
            conversation_history,
            lexicon,
            stats,
            df_generic=_df_generic(),
        )
        engine.save_lexicon(lexicon, _LEXICON_PATH)
        engine.save_stats(stats, _STATS_PATH)
        # Session-Puffer (Task 3): letzte Antwort für Folge-Injektionen merken
        _session_ctx["last_response"] = str(assistant_response)
        return

    ctx.register_hook("pre_llm_call", inject)
    ctx.register_hook("pre_tool_call", on_tool)
    ctx.register_hook("post_tool_call", on_tool_result)
    ctx.register_hook("post_llm_call", on_llm_response)
