"""Evidence-based candidate selector."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from .evidence import evidence_for
from .models import CandidateDecision, Evidence, RoutingDecision, SkillRecord

MAX_CANDIDATES = 3


def _canonical_set(values: Iterable[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


def _learned_evidence(message: str, skill_name: str, learned: Mapping[str, Mapping[str, int]]) -> tuple[Evidence, ...]:
    from .evidence import tokens

    result: list[Evidence] = []
    for word in tokens(message):
        support = int(learned.get(word, {}).get(skill_name, 0))
        if support >= 2:
            result.append(Evidence("learned", word, min(4.0, 1.0 + support / 4), f"verifiziertes Lernsignal ({support})"))
    return tuple(result)


def select(
    message: str,
    skills: Iterable[SkillRecord],
    *,
    already_loaded: Iterable[str] = (),
    learned: Mapping[str, Mapping[str, int]] | None = None,
) -> RoutingDecision:
    loaded = _canonical_set(already_loaded)
    learned = learned or {}
    candidates: list[CandidateDecision] = []
    rejected: list[CandidateDecision] = []
    seen: set[str] = set()
    for skill in skills:
        canonical = skill.canonical_name
        if canonical in seen:
            continue
        seen.add(canonical)
        evidence = evidence_for(message, skill) + _learned_evidence(message, canonical, learned)
        is_loaded = canonical in loaded
        if is_loaded:
            rejected.append(CandidateDecision(skill, "reject", 1.0, evidence, "bereits systemseitig geladen", True))
            continue
        score = sum(item.weight for item in evidence)
        distinct_kinds = {item.kind for item in evidence}
        if score < 3.0 or not evidence:
            rejected.append(CandidateDecision(skill, "reject", score / 10, evidence, "keine ausreichende Evidenz"))
            continue
        confidence = min(0.99, score / 10 + (0.12 if len(distinct_kinds) > 1 else 0.0))
        decision = "required" if any(item.kind == "name" for item in evidence) else "recommended"
        candidates.append(CandidateDecision(skill, decision, confidence, evidence, "mehrere taskbezogene Evidenzen" if len(distinct_kinds) > 1 else "taskbezogene Evidenz"))
    candidates.sort(key=lambda item: (-item.confidence, item.skill.canonical_name))
    overflow = candidates[MAX_CANDIDATES:]
    candidates = candidates[:MAX_CANDIDATES]
    rejected.extend(
        replace(item, decision="reject", reason="Kandidatenbudget überschritten")
        for item in overflow
    )
    fallback = None if candidates else "no_high_confidence_match"
    return RoutingDecision(tuple(candidates), tuple(rejected), fallback)
