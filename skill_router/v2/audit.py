"""Privacy-filtered append-only routing audit."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter
from pathlib import Path

from .models import RoutingDecision

_LOCK = threading.Lock()


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def record(path: Path, session_id: str, decision: RoutingDecision, *, plugin_version: str = "0.7.0") -> None:
    accepted = list(decision.candidates)
    evidence_kinds = Counter(
        evidence.kind
        for item in accepted
        for evidence in item.evidence
    )
    confidence = [item.confidence for item in accepted]
    budget_rejections = sum(item.reason == "Kandidatenbudget überschritten" for item in decision.rejected)
    event = {
        "ts": time.time(),
        "session": _session_hash(session_id) if session_id else None,
        "plugin_version": plugin_version,
        "accepted": [item.skill.name for item in accepted],
        "accepted_count": len(accepted),
        "rejected_count": len(decision.rejected),
        "budget_rejections": budget_rejections,
        "evidence": [{item.skill.name: sorted({ev.kind for ev in item.evidence})} for item in accepted],
        "evidence_kind_counts": dict(sorted(evidence_kinds.items())),
        "confidence_max": max(confidence, default=0.0),
        "confidence_min": min(confidence, default=0.0),
        "confidence_avg": sum(confidence) / len(confidence) if confidence else 0.0,
        "estimated_chars": sum(len(item.skill.name) + 48 for item in accepted),
        "fallback_reason": decision.fallback_reason,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return
