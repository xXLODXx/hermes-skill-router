"""Evidence-based candidate selector."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from .evidence import evidence_for
from .models import (
    CandidateDecision,
    DecisionKind,
    Evidence,
    RoutingDecision,
    SkillRecord,
)

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
    matrix: Mapping[str, tuple[Evidence, ...]] | None = None,
) -> RoutingDecision:
    loaded = _canonical_set(already_loaded)
    learned = learned or {}
    matrix = matrix or {}
    candidates: list[CandidateDecision] = []
    rejected: list[CandidateDecision] = []
    seen: set[str] = set()
    for skill in skills:
        canonical = skill.canonical_name
        if canonical in seen:
            continue
        seen.add(canonical)
        evidence = evidence_for(message, skill) + _learned_evidence(message, canonical, learned) + matrix.get(canonical, ())
        is_loaded = canonical in loaded
        if is_loaded:
            rejected.append(CandidateDecision(skill, "reject", 1.0, evidence, "bereits systemseitig geladen", True))
            continue
        score = sum(item.weight for item in evidence)
        distinct_kinds = {item.kind for item in evidence}
        has_exact_evidence = any(item.kind in {"name", "tag", "description", "learned", "matrix"} for item in evidence)
        is_matrix_required = any(item.kind == "matrix" and "Pflicht" in item.detail for item in evidence)
        if score < 3.0 or not evidence or not has_exact_evidence:
            reason = "keine ausreichende Evidenz" if has_exact_evidence else "isoliertes Stamm-/Teilwortsignal"
            rejected.append(CandidateDecision(skill, "reject", score / 10, evidence, reason))
            continue
        confidence = min(0.99, score / 10 + (0.12 if len(distinct_kinds) > 1 else 0.0))
        decision: DecisionKind = "required" if is_matrix_required or any(item.kind == "name" for item in evidence) else "recommended"
        candidates.append(CandidateDecision(skill, decision, confidence, evidence, "mehrere taskbezogene Evidenzen" if len(distinct_kinds) > 1 else "taskbezogene Evidenz"))
    def ranking(item: CandidateDecision) -> tuple[float, float, str]:
        exact_score = sum(
            evidence.weight
            for evidence in item.evidence
            if evidence.kind != "subword"
        )
        return (-item.confidence, -exact_score, item.skill.canonical_name)

    candidates.sort(key=ranking)
    required = [item for item in candidates if item.decision == "required" and any(ev.kind == "matrix" for ev in item.evidence)]
    discovered = [item for item in candidates if item not in required]
    candidates = required + discovered[: max(0, MAX_CANDIDATES - len(required))]
    overflow = [item for item in discovered if item not in candidates]
    rejected.extend(
        replace(item, decision="reject", reason="Kandidatenbudget überschritten")
        for item in overflow
    )
    fallback = None if candidates else "no_high_confidence_match"
    return RoutingDecision(tuple(candidates), tuple(rejected), fallback)
