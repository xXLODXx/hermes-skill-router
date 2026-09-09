"""Privacy-filtered append-only routing audit."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

from .models import RoutingDecision

_LOCK = threading.Lock()


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def record(path: Path, session_id: str, decision: RoutingDecision, *, plugin_version: str = "2") -> None:
    event = {
        "ts": time.time(),
        "session": _session_hash(session_id) if session_id else None,
        "plugin_version": plugin_version,
        "accepted": [item.skill.name for item in decision.candidates],
        "rejected": len(decision.rejected),
        "evidence": [{item.skill.name: sorted({ev.kind for ev in item.evidence})} for item in decision.candidates],
        "estimated_chars": sum(len(item.skill.name) + 48 for item in decision.candidates),
        "fallback_reason": decision.fallback_reason,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return
