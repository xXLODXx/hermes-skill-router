"""Privacy-filtered append-only routing audit."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter
from pathlib import Path

from ..version import plugin_version as _plugin_version
from .models import RoutingDecision

_LOCK = threading.Lock()
_MAX_REJECTED = 5


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def _top_rejected(decision: RoutingDecision) -> list[dict]:
    """Up to five strongest rejects — the tuning input for future releases."""
    ranked = sorted(decision.rejected, key=lambda item: (-item.confidence, item.skill.name))
    return [
        {
            "name": item.skill.name[:64],
            "confidence": round(item.confidence, 2),
            "reason": item.reason[:48],
        }
        for item in ranked[:_MAX_REJECTED]
        if item.skill.name
    ]


def record(
    path: Path,
    session_id: str,
    decision: RoutingDecision,
    *,
    plugin_version: str | None = None,
    catalog_size: int = 0,
    profile: str = "",
    matrix_source: str = "",
    rescue: bool = False,
    fallback_emitted: bool = False,
    rendered_chars: int = 0,
) -> None:
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
        "plugin_version": plugin_version or _plugin_version(),
        "profile": profile,
        "catalog_size": int(catalog_size),
        "matrix_source": matrix_source,
        "rescue": bool(rescue),
        "fallback_emitted": bool(fallback_emitted),
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
        "rendered_chars": int(rendered_chars),
        "top_rejected": _top_rejected(decision),
        "fallback_reason": decision.fallback_reason,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return
