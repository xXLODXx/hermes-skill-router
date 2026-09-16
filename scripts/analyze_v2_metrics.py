#!/usr/bin/env python3
"""Summarize privacy-filtered skill-router v2 audit events."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def analyze(path: Path) -> dict[str, object]:
    events: list[dict] = []
    invalid = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                invalid += 1

    accepted = [name for event in events for name in event.get("accepted", [])]
    evidence = Counter()
    for event in events:
        evidence.update(event.get("evidence_kind_counts", {}))
    injections = sum(bool(event.get("accepted")) for event in events)
    fallbacks = sum(bool(event.get("fallback_reason")) for event in events)
    rendered = [int(event.get("rendered_chars", 0)) for event in events]
    profiles = Counter(str(event.get("profile") or "unknown") for event in events)
    catalogs = Counter(int(event.get("catalog_size", 0)) for event in events)
    return {
        "events": len(events),
        "invalid_lines": invalid,
        "sessions_hashed": len({event.get("session") for event in events if event.get("session")}),
        "plugin_versions": dict(Counter(str(event.get("plugin_version", "unknown")) for event in events)),
        "profiles": dict(sorted(profiles.items())),
        "catalog_sizes": dict(sorted(catalogs.items())),
        "injections": injections,
        "fallbacks": fallbacks,
        "rescued_events": sum(bool(event.get("rescue")) for event in events),
        "fallback_emitted": sum(bool(event.get("fallback_emitted")) for event in events),
        "fallback_rate": fallbacks / len(events) if events else 0.0,
        "injection_rate": injections / len(events) if events else 0.0,
        "accepted_candidates": sum(int(event.get("accepted_count", len(event.get("accepted", [])))) for event in events),
        "rejected_candidates": sum(int(event.get("rejected_count", 0)) for event in events),
        "budget_rejections": sum(int(event.get("budget_rejections", 0)) for event in events),
        "avg_candidates_per_event": sum(int(event.get("accepted_count", len(event.get("accepted", [])))) for event in events) / len(events) if events else 0.0,
        "avg_estimated_chars": sum(int(event.get("estimated_chars", 0)) for event in events) / len(events) if events else 0.0,
        "avg_rendered_chars": sum(rendered) / len(rendered) if rendered else 0.0,
        "avg_confidence": sum(float(event.get("confidence_avg", 0.0)) for event in events) / len(events) if events else 0.0,
        "evidence_kind_counts": dict(sorted(evidence.items())),
        "top_skills": Counter(accepted).most_common(20),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.audit), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
