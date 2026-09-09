"""Thread-safe, session-keyed volatile state."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

from .models import SessionTurn


class SessionStore:
    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self._ttl = ttl_seconds
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
            self._items[session_id] = (now, replace(current, **changes))

    def size(self) -> int:
        with self._lock:
            self._cleanup(time.monotonic())
            return len(self._items)
