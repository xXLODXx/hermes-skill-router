"""Thread-safe, session-keyed volatile state."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from typing import Any, cast

from .models import SessionTurn


def _ttl_from_env() -> float:
    """Session-state TTL; ``SKILL_ROUTER_SESSION_TTL`` overrides the 1h default."""
    raw = os.environ.get("SKILL_ROUTER_SESSION_TTL", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return 3600.0


class SessionStore:
    def __init__(self, ttl_seconds: float | None = None) -> None:
        self._ttl = _ttl_from_env() if ttl_seconds is None else ttl_seconds
        self._items: dict[str, tuple[float, SessionTurn]] = {}
        self._lock = threading.RLock()

    def _cleanup(self, now: float) -> None:
        expired = [key for key, (seen, _) in self._items.items() if now - seen > self._ttl]
        for key in expired:
            self._items.pop(key, None)

    def begin(self, session_id: str, message: str) -> SessionTurn | None:
        if not session_id:
            return None
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            old = self._items.get(session_id, (0.0, SessionTurn(session_id)))[1]
            turn = replace(old, message=message, turn_id=old.turn_id + 1)
            self._items[session_id] = (now, turn)
            return replace(turn, injected=set(turn.injected), already_loaded=set(turn.already_loaded))

    def get(self, session_id: str) -> SessionTurn | None:
        if not session_id:
            return None
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            item = self._items.get(session_id)
            if item is None:
                return None
            self._items[session_id] = (now, item[1])
            turn = item[1]
            return replace(turn, injected=set(turn.injected), already_loaded=set(turn.already_loaded))

    def update(self, session_id: str, **changes: object) -> None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(session_id)
            if item is None:
                return
            current = item[1]
            self._items[session_id] = (now, replace(current, **cast(Any, changes)))

    def size(self) -> int:
        with self._lock:
            self._cleanup(time.monotonic())
            return len(self._items)
